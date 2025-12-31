import re
from typing import Dict, List, Tuple, Optional

# Détecteurs de bornes
RE_START = re.compile(r"\bR[ÉE]SUM[ÉE]\s+DES\s+CARACT[ÉE]RISTIQUES\s+DU\s+PRODUIT\b", re.I)
RE_ANNEXE_II = re.compile(r"^\s*ANNEXE\s+II\b", re.I)

# Titres attendus (robuste aux accents)
RE_MAIN = re.compile(r"^\s*(\d{1,2})\.\s*(.*)$")
RE_SUB = re.compile(r"^\s*(\d{1,2})\.(\d)\.\s*(.*)$")

# On limite aux sections du RCP
VALID_MAIN = {str(i) for i in range(1, 11)}
VALID_SUB = {
    **{f"4.{i}": True for i in range(1, 10)},
    **{f"5.{i}": True for i in range(1, 4)},
    **{f"6.{i}": True for i in range(1, 7)},
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def extract_annexe_i_smpc_lines(full_text: str) -> List[str]:
    """
    Retourne uniquement les lignes de l'ANNEXE I (SmPC) :
    - démarre au premier "RÉSUMÉ DES CARACTÉRISTIQUES DU PRODUIT"
    - s'arrête à "ANNEXE II"
    """
    lines = [l.rstrip() for l in (full_text or "").splitlines()]

    # Trouver start
    start_idx: Optional[int] = None
    for i, l in enumerate(lines):
        if RE_START.search(l):
            start_idx = i
            break
    if start_idx is None:
        # fallback: prendre tout (mais tu verras vite que c’est mauvais)
        return [l for l in lines if _norm(l)]

    # Tronquer jusqu'à annexe II
    out: List[str] = []
    for l in lines[start_idx:]:
        if RE_ANNEXE_II.match(l):
            break
        if _norm(l):
            out.append(_norm(l))
    return out

def parse_smpc_sections(full_text: str) -> Dict[str, str]:
    """
    Construit un dict {"1": "...", "4.1": "..."} pour le RCP.
    Gestion du cas où le PDF écrit "1." sur une ligne puis le titre sur la ligne suivante.
    """
    lines = extract_annexe_i_smpc_lines(full_text)

    sections: Dict[str, List[str]] = {}
    current_key: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Cas "4.1. Titre"
        msub = RE_SUB.match(line)
        if msub:
            key = f"{msub.group(1)}.{msub.group(2)}"
            title = _norm(msub.group(3))
            if key in VALID_SUB:
                current_key = key
                sections.setdefault(current_key, [])
                if title:
                    sections[current_key].append(f"{key}. {title}")
            i += 1
            continue

        # Cas "1. TITRE" ou "1." seul
        mm = RE_MAIN.match(line)
        if mm:
            key = mm.group(1)
            rest = _norm(mm.group(2))

            if key in VALID_MAIN:
                # Si c'est juste "1." sans titre, prendre la prochaine ligne comme titre
                title = rest
                if title == "" and (i + 1) < len(lines):
                    nxt = _norm(lines[i + 1])
                    # si la prochaine ligne ressemble à un vrai titre
                    if nxt and not RE_MAIN.match(nxt) and not RE_SUB.match(nxt):
                        title = nxt
                        i += 1  # consomme la ligne de titre

                current_key = key
                sections.setdefault(current_key, [])
                if title:
                    sections[current_key].append(f"{key}. {title}")
                i += 1
                continue

        # Contenu normal -> rattacher à la section courante
        if current_key:
            sections[current_key].append(line)

        i += 1

    # Convert list->string
    return {k: "\n".join(v).strip() for k, v in sections.items()}
