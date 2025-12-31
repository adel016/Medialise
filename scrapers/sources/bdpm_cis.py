# scrapers/sources/bdpm_cis.py
from __future__ import annotations

from typing import List
import pandas as pd


def iter_cis_codes(cis_bdpm_csv_path: str) -> List[str]:
    """
    Retourne la liste des CIS depuis CIS_bdpm.csv.
    Lecture robuste (tabulation + encodages fréquents).
    """
    last_err = None
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(
                cis_bdpm_csv_path,
                sep="\t",
                header=None,
                dtype=str,
                encoding=enc,
            )
            cis = df.iloc[:, 0].dropna().astype(str).str.strip()
            cis = cis[cis.str.fullmatch(r"\d{8}")].drop_duplicates().tolist()
            return cis
        except Exception as e:
            last_err = e

    raise RuntimeError(
        f"Impossible de lire {cis_bdpm_csv_path} (encodage ou format). Dernière erreur: {last_err}"
    )
