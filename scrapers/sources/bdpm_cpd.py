# scrapers/sources/bdpm_cpd.py
from __future__ import annotations

import os
import re
import time
from typing import Dict, Optional

import pandas as pd

from scrapers.utils.mongo import get_collection


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def load_cis_cpd_map(cpd_path: Optional[str] = None) -> Dict[str, str]:
    """
    Charge CIS_CPD_bdpm.csv et retourne {CIS: texte_condition}.
    Le CSV BDPM est TAB-separated et souvent en latin-1/cp1252.
    """
    if cpd_path is None:
        root = _project_root()
        cpd_path = os.path.join(root, "data", "bdpm", "CIS_CPD_bdpm.csv")

    if not os.path.exists(cpd_path):
        raise FileNotFoundError(f"Fichier BDPM introuvable: {cpd_path}")

    last_err = None
    df = None
    for enc in ("utf-8", "latin-1", "cp1252", "ISO-8859-1"):
        try:
            df = pd.read_csv(
                cpd_path,
                sep="\t",
                header=None,
                dtype=str,
                encoding=enc,
            )
            break
        except Exception as e:
            last_err = e

    if df is None:
        raise RuntimeError(f"Impossible de lire {cpd_path}. Dernière erreur: {last_err}")

    cis_to_cpd: Dict[str, str] = {}

    # Format attendu: <CIS>\t<Texte CPD>
    for _, row in df.iterrows():
        cis = str(row.iloc[0]).strip() if len(row) > 0 else ""
        cpd = str(row.iloc[1]).strip() if len(row) > 1 else ""

        if cis.isdigit() and len(cis) == 8 and cpd:
            cis_to_cpd[cis] = cpd

    return cis_to_cpd


def _extract_specid_as_cis(url: str) -> Optional[str]:
    """
    Extrait specid=... depuis une URL BDPM/ANSM.
    On le traite comme CIS (dans ton cas vos docs ont url=affichageDoc.php?specid=...).
    """
    if not url:
        return None
    m = re.search(r"[?&]specid=(\d+)", url)
    return m.group(1) if m else None


def enrich_medicines_with_cpd(
    collection_name: str = "medicines",
    cpd_path: Optional[str] = None,
    sleep_s: float = 0.0,
) -> dict:
    """
    Enrichit Mongo (collection medicines) avec:
      - bdpm.cis
      - bdpm.has_cpd
      - bdpm.cpd (si présent)
      - bdpm.cpd_updated_at
    """
    col = get_collection(collection_name)
    cis_to_cpd = load_cis_cpd_map(cpd_path=cpd_path)

    scanned = 0
    with_cpd = 0
    modified = 0
    now_ts = int(time.time())

    cursor = col.find({"url": {"$type": "string"}}, {"_id": 1, "url": 1})

    for doc in cursor:
        scanned += 1
        cis = _extract_specid_as_cis(doc.get("url", ""))
        if not cis:
            continue

        cpd = cis_to_cpd.get(cis)
        has_cpd = bool(cpd)

        update_set = {
            "bdpm.cis": cis,
            "bdpm.has_cpd": has_cpd,
            "bdpm.cpd_updated_at": now_ts,
        }

        if has_cpd:
            update_set["bdpm.cpd"] = cpd
            with_cpd += 1
            res = col.update_one({"_id": doc["_id"]}, {"$set": update_set})
        else:
            res = col.update_one(
                {"_id": doc["_id"]},
                {"$set": update_set, "$unset": {"bdpm.cpd": ""}},
            )

        modified += res.modified_count

        if sleep_s and sleep_s > 0:
            time.sleep(sleep_s)

    return {"scanned": scanned, "with_cpd": with_cpd, "modified": modified}
