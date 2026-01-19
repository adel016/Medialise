# scrapers/sources/bdpm_compo.py
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd

from scrapers.utils.mongo import get_collection  # :contentReference[oaicite:0]{index=0}


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def _iter_bdpm_compo_rows(path: str):
    """
    Lecture robuste CIS_COMPO_bdpm.csv.

    Règle forte BDPM COMPO:
      - les 2 derniers champs sont toujours: TYPE (SA/FT) et RANK (entier)
    Donc si une ligne contient des tabulations parasites, on recolle la partie centrale
    en conservant ces 2 derniers champs.
    """
    last_err = None
    for enc in ("utf-8", "latin-1", "cp1252", "ISO-8859-1"):
        try:
            with open(path, "r", encoding=enc, errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue

                    parts = line.split("\t")
                    if len(parts) < 8:
                        continue

                    # Nettoyage espaces
                    parts = [p.strip() for p in parts]

                    # On force TYPE et RANK depuis la fin
                    typ = parts[-2].upper() if len(parts) >= 2 else ""
                    rank = parts[-1]

                    # Si typ/rank ne sont pas valides, on tente un fallback simple
                    # (au cas où des tabs en trop déplacent un peu)
                    def is_type(x: str) -> bool:
                        return x.upper() in {"SA", "FT"}

                    def is_rank(x: str) -> bool:
                        return x.isdigit()

                    if not (is_type(typ) and is_rank(rank)):
                        # essaie de retrouver type/rank en scannant la fin
                        found = False
                        for i in range(len(parts) - 1, 0, -1):
                            if is_rank(parts[i]) and is_type(parts[i - 1]):
                                typ = parts[i - 1].upper()
                                rank = parts[i]
                                head = parts[: i - 1]
                                parts = head + [typ, rank]
                                found = True
                                break
                        if not found:
                            # ligne irrécupérable -> skip
                            continue

                    # Maintenant on reconstruit les 6 premiers champs (0..5) + type + rank
                    head = parts[:-2]  # tout sauf type/rank
                    # head devrait contenir CIS, forme, code, libellé, dosage, référence
                    # si head a plus de 6 champs, on recolle l'excédent dans la référence
                    if len(head) < 6:
                        continue
                    if len(head) > 6:
                        head = head[:5] + [" ".join(head[5:])]

                    yield head + [typ, rank]  # toujours 8 colonnes
            return
        except Exception as e:
            last_err = e

    raise RuntimeError(f"Impossible de lire {path}. Dernière erreur: {last_err}")


def load_compo_map(compo_path: Optional[str] = None) -> Dict[str, List[dict]]:
    """
    Retourne {CIS: [entries...]} à partir de CIS_COMPO_bdpm.csv

    Colonnes attendues:
      0 CIS
      1 Forme
      2 Code substance
      3 Libellé substance
      4 Dosage
      5 Référence (ex: un comprimé / 2 ml...)
      6 Type (SA/FT)
      7 Rang (ordre)
    """
    if compo_path is None:
        root = _project_root()
        compo_path = os.path.join(root, "data", "bdpm", "CIS_COMPO_bdpm.csv")

    if not os.path.exists(compo_path):
        raise FileNotFoundError(f"Fichier COMPO introuvable: {compo_path}")

    compo: Dict[str, List[dict]] = {}

    for parts in _iter_bdpm_compo_rows(compo_path):
        cis = parts[0].strip()
        forme = parts[1].strip()
        sub_code = parts[2].strip()
        sub_label = parts[3].strip()
        dosage = parts[4].strip()
        reference = parts[5].strip()
        typ = parts[6].strip()
        rang_str = parts[7].strip()

        if not (cis.isdigit() and len(cis) == 8):
            continue

        rang = int(rang_str) if rang_str.isdigit() else None

        entry = {
            "forme": forme,
            "substance_code": sub_code,
            "substance_label": sub_label,
            "dosage": dosage,
            "reference": reference,
            "type": typ,   # SA / FT
            "rank": rang,
        }

        compo.setdefault(cis, []).append(entry)

    # tri par rank (None à la fin)
    def sort_key(e: dict):
        return (e["rank"] is None, e["rank"] if e["rank"] is not None else 10**9)

    for cis in compo:
        compo[cis] = sorted(compo[cis], key=sort_key)

    return compo


def _extract_cis_from_doc(doc: dict) -> Optional[str]:
    bdpm = doc.get("bdpm") or {}
    cis = bdpm.get("cis")
    if isinstance(cis, str) and cis.isdigit() and len(cis) == 8:
        return cis

    url = doc.get("url", "")
    if not isinstance(url, str):
        return None
    m = re.search(r"[?&]specid=(\d+)", url)
    return m.group(1) if m else None


def enrich_medicines_with_compo(
    collection_name: str = "medicines",
    compo_path: Optional[str] = None,
    sleep_s: float = 0.0,
) -> dict:
    """
    Ajoute / met à jour dans Mongo:
      - bdpm.compo_entries (liste détaillée)
      - bdpm.compo_sa_substances (liste unique des SA)
      - bdpm.has_compo
      - bdpm.compo_updated_at
    """
    col = get_collection(collection_name)
    compo_map = load_compo_map(compo_path=compo_path)

    scanned = 0
    with_compo = 0
    modified = 0
    now_ts = int(time.time())

    cursor = col.find({"url": {"$type": "string"}}, {"_id": 1, "url": 1, "bdpm": 1})

    for doc in cursor:
        scanned += 1
        cis = _extract_cis_from_doc(doc)
        if not cis:
            continue

        entries = compo_map.get(cis, [])
        has_compo = bool(entries)

        update_set = {
            "bdpm.cis": cis,
            "bdpm.has_compo": has_compo,
            "bdpm.compo_updated_at": now_ts,
        }

        unset = {}
        if has_compo:
            with_compo += 1
            update_set["bdpm.compo_entries"] = entries

            # SA uniques (substances actives)
            sa = []
            seen = set()
            for e in entries:
                if (e.get("type") or "").upper() == "SA":
                    label = (e.get("substance_label") or "").strip()
                    if label and label not in seen:
                        seen.add(label)
                        sa.append(label)
            update_set["bdpm.compo_sa_substances"] = sa
        else:
            unset["bdpm.compo_entries"] = ""
            unset["bdpm.compo_sa_substances"] = ""

        if unset:
            res = col.update_one({"_id": doc["_id"]}, {"$set": update_set, "$unset": unset})
        else:
            res = col.update_one({"_id": doc["_id"]}, {"$set": update_set})

        modified += res.modified_count

        if sleep_s and sleep_s > 0:
            time.sleep(sleep_s)

    return {"scanned": scanned, "with_compo": with_compo, "modified": modified}
