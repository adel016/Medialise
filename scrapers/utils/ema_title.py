# scrapers/utils/ema_title.py

from __future__ import annotations
import re
from typing import Dict, Optional


def extract_ema_title_from_sections(rcp_sections: Dict[str, str]) -> Optional[str]:
    """
    Essaie d'extraire le nom du médicament depuis la section 1 (EMA).
    Retourne un titre court (ex: "OPDIVO") ou None.
    """
    s1 = rcp_sections.get("1")
    if not s1:
        return None

    lines = [l.strip() for l in s1.splitlines() if l.strip()]
    if len(lines) < 2:
        return None

    # Ligne la plus probable contenant le nom + dosage/forme
    candidate = lines[1]

    # Exemple: "OPDIVO 10 mg/ml, solution à diluer pour perfusion"
    # On coupe avant dosage/virgule/parenthèse
    candidate = re.split(r"\s+\d|,|\(|–| - ", candidate, maxsplit=1)[0].strip()

    candidate = re.sub(r"\s+", " ", candidate).strip()
    if len(candidate) < 2:
        return None

    return candidate


def normalize_for_search(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s
