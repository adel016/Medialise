# scrapers/sources/theriaque_html.py
import re
import html
import requests
from typing import Any
from bs4 import BeautifulSoup
import re


THERIAQUE_BASE = "https://www.theriaque.org"


def resolve_sp_id_from_cis(cis: str, session: requests.Session) -> int | None:
    """
    Résout un CIS (ex: 62869109) vers un sp_id Thériaque (ex: 4552)
    en appelant l'endpoint datagrid iframe.

    Nécessite une session AUTH (cookies OK).
    """
    cis = str(cis).strip()
    if not cis:
        return None

    url = (
        f"{THERIAQUE_BASE}/apps/recherche/rch_datagrid_iframe.php"
        f"?critere=SIMPLE_CIP&type=TOUS&search={cis}"
        f"&id_page=3&orderBy=nom&direction=ASC&page=1&typeIndic="
    )

    r = session.get(url, timeout=30)
    txt = r.text or ""

    # Debug utile si jamais ça casse plus tard
    if "Veuillez vous identifier" in txt:
        # pas loggé / cookie expiré
        return None

    # Cas 1: onclick window.open("...type=SP&id=4552")
    m = re.search(r"type=SP&amp;id=(\d+)", txt)
    if m:
        return int(m.group(1))

    # Cas 2: parfois l'HTML n'est pas encodé en &amp;
    m = re.search(r"type=SP&id=(\d+)", txt)
    if m:
        return int(m.group(1))

    # Cas 3: fallback: id=4552 dans l'URL monographie
    m = re.search(r"/apps/monographie/index\.php\?type=SP[^\"']*id=(\d+)", txt)
    if m:
        return int(m.group(1))

    return None


def _strip_tags_keep_text(html_text: str) -> str:
    # supprime tags HTML, garde le texte
    html_text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I)
    html_text = re.sub(r"</p\s*>", "\n", html_text, flags=re.I)
    html_text = re.sub(r"<[^>]+>", " ", html_text)
    html_text = html.unescape(html_text)
    # clean spaces
    html_text = re.sub(r"[ \t]+", " ", html_text)
    html_text = re.sub(r"\n\s+\n", "\n", html_text)
    return html_text.strip()


def _clean_text(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _extract_rubrique(html_text: str, rubrique_id: str) -> str:
    """
    Extrait le contenu HTML à l'intérieur de:
      <div id='XXX' class='rubrique'> ... </div>
    en restant au plus près (non-greedy).
    """
    m = re.search(
        rf"<div[^>]+id=['\"]{re.escape(rubrique_id)}['\"][^>]*class=['\"]rubrique['\"][^>]*>(.*?)</div>\s*</div>",
        html_text,
        flags=re.S | re.I
    )
    return m.group(1) if m else ""

def _first_table_mono(rubrique_html: str) -> str:
    m = re.search(
        r"<table[^>]*class=['\"]table_mono['\"][^>]*>(.*?)</table>",
        rubrique_html,
        flags=re.S | re.I
    )
    return m.group(0) if m else ""

def fetch_theriaque_interactions(sp_id: str, session: requests.Session) -> dict[str, Any]:
    """
    Récupère la rubrique INTER (Interactions médicamenteuses) et renvoie:
    {
      "sp_id": "...",
      "url": "...",
      "text": "...",
      "ref_officielle": "..." (si trouvée)
    }
    """
    url = f"{THERIAQUE_BASE}/apps/monographie/index.php?type=SP&id={sp_id}&info=INTER"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    html_text = r.text

    rubrique = _extract_rubrique(html_text, "inter")
    if not rubrique:
        return {"sp_id": str(sp_id), "url": url, "error": "rubrique inter not found (auth/page changed)"}

    table = _first_table_mono(rubrique)
    if not table:
        return {"sp_id": str(sp_id), "url": url, "error": "table_mono not found in inter rubrique"}

    # Le texte utile est généralement dans le 1er <td colspan="2">...</td>
    m_td = re.search(r"<td[^>]*colspan=['\"]2['\"][^>]*>(.*?)</td>", table, flags=re.S | re.I)
    main_text = _clean_text(m_td.group(1)) if m_td else _clean_text(table)

    # Référence(s) officielle(s) : on tente d’extraire la ligne si présente
    m_ref = re.search(r"Référence\(s\)\s*officielle\(s\).*?:\s*(.*?)</td>", table, flags=re.S | re.I)
    ref = _clean_text(m_ref.group(1)) if m_ref else None

    return {
        "sp_id": str(sp_id),
        "url": url,
        "text": main_text,
        "ref_officielle": ref
    }

def fetch_theriaque_c_indic(sp_id: str, session):
    url = f"https://www.theriaque.org/apps/monographie/index.php?type=SP&id={sp_id}&info=C_INDIC"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return {"sp_id": str(sp_id), "url": url, "html": r.text}


def parse_theriaque_c_indic(html: str) -> dict:
    """
    Parse la rubrique Thériaque "Contre-indications" (info=C_INDIC).

    Retour final (schéma cible):
    {
      "terrains": [
        {
          "terrain_no": 1,
          "intitule": "HYPERSENSIBILITE",
          "details": ["..."],
          "niveau": ["CONTRE-INDICATION ABSOLUE"],
          "references": ["Rectificatif ..."],
          "cim10": ["T784", "T887", "Z888", "Y574", "Y577"]
        }, ...
      ],
      "commentaires_rcp": "- ...",
      "ref_officielle": "Rectificatif ..."
    }
    """
    soup = BeautifulSoup(html, "html.parser")

    def clean(s: str) -> str:
        return " ".join((s or "").split()).strip()

    def text_of(node) -> str:
        if not node:
            return ""
        return clean(node.get_text(" ", strip=True))

    def list_items(node):
        if not node:
            return []
        lis = node.find_all("li")
        if lis:
            out = []
            for li in lis:
                t = text_of(li)
                if t:
                    out.append(t)
            return out
        t = text_of(node)
        return [t] if t else []

    def extract_cim10_codes(items: list[str]) -> list[str]:
        """
        Normalise CIM10:
        - "Allergie ... T784" -> "T784"
        - "Malabsorption intestinale K90" -> "K90"
        - "Non concerné ." -> ignoré
        """
        codes = []
        for it in items:
            s = clean(it)

            # ignore valeurs inutiles
            if not s or "non concern" in s.lower():
                continue

            # capture codes CIM10:
            # - T784 / Z888 / Y574 etc. (lettre + chiffres)
            # - K90 (lettre + 2 chiffres) parfois sans 4e char
            # - K908 (lettre + 3 chiffres)
            m_all = re.findall(r"\b([A-Z][0-9]{2,3}[0-9A-Z]?)\b", s)
            if m_all:
                codes.append(m_all[-1])
            else:
                # fallback: si rien ne match, on garde texte brut (rare)
                codes.append(s)

        # dédoublonnage en gardant l'ordre
        seen = set()
        uniq = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        return uniq


    tables = soup.find_all("table", class_="table_mono")

    terrains = []
    commentaires_rcp = ""
    ref_officielle = ""

    terrain_re = re.compile(r"Terrain\s*N[°o]\s*(\d+)", re.IGNORECASE)

    # -----------------------------
    # 1) Terrains
    # -----------------------------
    for t in tables:
        rows = t.find_all("tr")
        if not rows:
            continue

        first_tds = rows[0].find_all("td")
        if len(first_tds) >= 1:
            left = text_of(first_tds[0])
            m = terrain_re.search(left)
            if not m:
                continue

            terrain_no = int(m.group(1))

            intitule = ""
            details = []

            if len(first_tds) >= 2:
                right = first_tds[1]
                b = right.find("b")
                intitule = text_of(b) if b else text_of(right)

                ul = right.find("ul")
                if ul:
                    details = [text_of(li) for li in ul.find_all("li") if text_of(li)]
                else:
                    details = []

            niveau = []
            references = []
            cim10 = []

            for r in rows[1:]:
                tds = r.find_all("td")
                if len(tds) < 2:
                    continue
                k = text_of(tds[0]).lower()
                v = tds[1]

                if "niveau" in k:
                    # souvent <ul><li><b>...</b>
                    niveau = list_items(v)
                elif "référence" in k or "reference" in k:
                    references = list_items(v)
                elif "cim" in k:
                    cim10_raw = list_items(v)
                    cim10 = extract_cim10_codes(cim10_raw)

            terrains.append({
                "terrain_no": terrain_no,
                "intitule": intitule,
                "details": details,
                "niveau": niveau,
                "references": references,
                "cim10": cim10,
            })

    # -----------------------------
    # 2) Commentaires du RCP
    # (dans ton HTML: <b>Commentaires du RCP</b><table class="table_mono">...)
    # -----------------------------
    marker = soup.find(string=lambda s: isinstance(s, str) and "Commentaires du RCP" in s)
    if marker:
        table = marker.find_parent().find_next("table", class_="table_mono")
        if table:
            div_text = table.find("div", class_="text")
            commentaires_rcp = text_of(div_text) if div_text else text_of(table)

            # Référence(s) officielle(s) dans la table commentaires
            for r in table.find_all("tr"):
                tds = r.find_all("td")
                if len(tds) >= 2 and "référence" in text_of(tds[0]).lower():
                    refs = list_items(tds[1])
                    if refs:
                        ref_officielle = refs[0]
                    break

    return {
        "terrains": terrains,
        "commentaires_rcp": commentaires_rcp,
        "ref_officielle": ref_officielle,
    }


def fetch_theriaque_indic(sp_id: str, session: requests.Session) -> dict[str, Any]:
    """
    Récupère la rubrique INDIC (Indications).
    """
    url = f"{THERIAQUE_BASE}/apps/monographie/index.php?type=SP&id={sp_id}&info=INDIC"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return {"sp_id": str(sp_id), "url": url, "html": r.text}


def parse_theriaque_indic(html_text: str) -> dict[str, Any]:
    """
    Parse rub INDIC, retourne un bloc simple (comme INTER):
    {
      "text": "...",
      "ref_officielle": "..." (si trouvée)
    }
    """
    # 1) Extraire la rubrique <div id='indic' class='rubrique'>...</div>
    rubrique = _extract_rubrique(html_text, "indic")
    if not rubrique:
        return {"text": "", "ref_officielle": None, "error": "rubrique indic not found (auth/page changed)"}

    # 2) Récupérer toutes les tables de la rubrique (parfois plusieurs)
    soup = BeautifulSoup(rubrique, "html.parser")
    tables = soup.find_all("table", class_="table_mono")
    if not tables:
        # fallback: texte brut de la rubrique
        return {"text": _clean_text(rubrique), "ref_officielle": None}

    # 3) Concaténer le texte utile (souvent dans td colspan=2, sinon texte table)
    chunks = []
    ref = None

    for t in tables:
        # texte principal
        td_main = t.find("td", attrs={"colspan": "2"})
        if td_main:
            chunks.append(_clean_text(str(td_main)))
        else:
            chunks.append(_clean_text(str(t)))

        # ref officielle (ligne "Référence(s) officielle(s)" si présente)
        # On cherche dans les rows
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                k = _clean_text(tds[0].get_text(" ", strip=True)).lower()
                if "référence" in k or "reference" in k:
                    candidate = _clean_text(tds[1].get_text(" ", strip=True))
                    if candidate:
                        ref = candidate

    text = "\n\n".join([c for c in chunks if c]).strip()

    return {
        "text": text,
        "ref_officielle": ref,
    }
