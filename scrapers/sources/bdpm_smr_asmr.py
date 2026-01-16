# scrapers/sources/bdpm_smr_asmr.py
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scrapers.utils.mongo import get_collection


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def _read_bdpm_tsv(path: str) -> pd.DataFrame:
    """
    Lit un fichier BDPM tabulé (TSV) avec encodages fréquents.
    Colonnes attendues (sans header):
      0 CIS
      1 Code dossier (ex: CT-xxxx)
      2 Libellé (ex: Inscription (CT))
      3 Date (YYYYMMDD)
      4 Valeur (ASMR: I..V, SMR: Important/Modéré/...)
      5 Commentaire
    """
    last_err = None
    for enc in ("utf-8", "latin-1", "cp1252", "ISO-8859-1"):
        try:
            df = pd.read_csv(path, sep="\t", header=None, dtype=str, encoding=enc)
            return df
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Impossible de lire {path}. Dernière erreur: {last_err}")


def _load_as_list(path: str) -> List[dict]:
    df = _read_bdpm_tsv(path)

    rows: List[dict] = []
    for _, r in df.iterrows():
        cis = str(r.iloc[0]).strip() if len(r) > 0 else ""
        dossier = str(r.iloc[1]).strip() if len(r) > 1 else ""
        event = str(r.iloc[2]).strip() if len(r) > 2 else ""
        date_str = str(r.iloc[3]).strip() if len(r) > 3 else ""
        value = str(r.iloc[4]).strip() if len(r) > 4 else ""
        comment = str(r.iloc[5]).strip() if len(r) > 5 else ""

        if not (cis.isdigit() and len(cis) == 8):
            continue

        # date -> int yyyymmdd si possible
        date_int = None
        if date_str.isdigit() and len(date_str) == 8:
            date_int = int(date_str)

        rows.append({
            "cis": cis,
            "dossier": dossier,
            "event": event,
            "date": date_int,
            "value": value,
            "comment": comment,
        })
    return rows


def load_as_maps(
    asmr_path: Optional[str] = None,
    smr_path: Optional[str] = None,
) -> Tuple[Dict[str, List[dict]], Dict[str, List[dict]]]:
    """
    Retourne:
      - asmr_map: {CIS: [entries...] }
      - smr_map:  {CIS: [entries...] }
    """
    root = _project_root()

    if asmr_path is None:
        asmr_path = os.path.join(root, "data", "bdpm", "CIS_HAS_ASMR_bdpm.csv")
    if smr_path is None:
        smr_path = os.path.join(root, "data", "bdpm", "CIS_HAS_SMR_bdpm.csv")

    if not os.path.exists(asmr_path):
        raise FileNotFoundError(f"Fichier ASMR introuvable: {asmr_path}")
    if not os.path.exists(smr_path):
        raise FileNotFoundError(f"Fichier SMR introuvable: {smr_path}")

    asmr_rows = _load_as_list(asmr_path)
    smr_rows = _load_as_list(smr_path)

    asmr_map: Dict[str, List[dict]] = {}
    smr_map: Dict[str, List[dict]] = {}

    for row in asmr_rows:
        asmr_map.setdefault(row["cis"], []).append(row)

    for row in smr_rows:
        smr_map.setdefault(row["cis"], []).append(row)

    # tri décroissant par date (None en dernier)
    def sort_key(x: dict):
        return (x["date"] is not None, x["date"] or 0)

    for cis in asmr_map:
        asmr_map[cis] = sorted(asmr_map[cis], key=sort_key, reverse=True)
    for cis in smr_map:
        smr_map[cis] = sorted(smr_map[cis], key=sort_key, reverse=True)

    return asmr_map, smr_map


def _extract_cis_from_doc(doc: dict) -> Optional[str]:
    """
    Récupère CIS depuis:
      - doc.bdpm.cis (si déjà enrichi)
      - sinon depuis url ?specid=...
    """
    bdpm = doc.get("bdpm") or {}
    cis = bdpm.get("cis")
    if isinstance(cis, str) and cis.isdigit():
        return cis

    url = doc.get("url", "")
    if not isinstance(url, str):
        return None
    m = re.search(r"[?&]specid=(\d+)", url)
    return m.group(1) if m else None


def enrich_medicines_with_smr_asmr(
    collection_name: str = "medicines",
    asmr_path: Optional[str] = None,
    smr_path: Optional[str] = None,
    sleep_s: float = 0.0,
) -> dict:
    """
    Enrichit la collection Mongo avec:
      - bdpm.asmr_entries (liste triée, date desc)
      - bdpm.smr_entries  (liste triée, date desc)
      - bdpm.asmr_latest (valeur la plus récente)
      - bdpm.smr_latest  (valeur la plus récente)
      - timestamps: bdpm.smr_asmr_updated_at
    """
    col = get_collection(collection_name)
    asmr_map, smr_map = load_as_maps(asmr_path=asmr_path, smr_path=smr_path)

    scanned = 0
    with_any = 0
    modified = 0
    now_ts = int(time.time())

    cursor = col.find({"url": {"$type": "string"}}, {"_id": 1, "url": 1, "bdpm": 1})

    for doc in cursor:
        scanned += 1
        cis = _extract_cis_from_doc(doc)
        if not cis or not (cis.isdigit() and len(cis) == 8):
            continue

        asmr_entries = asmr_map.get(cis, [])
        smr_entries = smr_map.get(cis, [])

        has_any = bool(asmr_entries or smr_entries)
        if has_any:
            with_any += 1

        update_set = {
            "bdpm.cis": cis,  # on assure la présence
            "bdpm.smr_asmr_updated_at": now_ts,
        }

        # latest (1er élément car tri desc)
        if asmr_entries:
            update_set["bdpm.asmr_entries"] = asmr_entries
            update_set["bdpm.asmr_latest"] = asmr_entries[0].get("value")
            update_set["bdpm.has_asmr"] = True
        else:
            update_set["bdpm.has_asmr"] = False

        if smr_entries:
            update_set["bdpm.smr_entries"] = smr_entries
            update_set["bdpm.smr_latest"] = smr_entries[0].get("value")
            update_set["bdpm.has_smr"] = True
        else:
            update_set["bdpm.has_smr"] = False

        # unset des champs vides pour garder des docs propres
        unset = {}
        if not asmr_entries:
            unset["bdpm.asmr_entries"] = ""
            unset["bdpm.asmr_latest"] = ""
        if not smr_entries:
            unset["bdpm.smr_entries"] = ""
            unset["bdpm.smr_latest"] = ""

        if unset:
            res = col.update_one({"_id": doc["_id"]}, {"$set": update_set, "$unset": unset})
        else:
            res = col.update_one({"_id": doc["_id"]}, {"$set": update_set})

        modified += res.modified_count

        if sleep_s and sleep_s > 0:
            time.sleep(sleep_s)

    return {"scanned": scanned, "with_any_smr_asmr": with_any, "modified": modified}
