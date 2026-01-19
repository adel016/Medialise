# scrapers/sources/theriaque_html.py
import re
import html
import requests
from typing import Any


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