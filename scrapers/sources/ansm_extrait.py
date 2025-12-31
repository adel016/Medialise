# scrapers/sources/ansm_extrait.py
from __future__ import annotations

import re
import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def _make_soup(resp: requests.Response) -> BeautifulSoup:
    # on garde simple et robuste
    try:
        return BeautifulSoup(resp.content, "html.parser")
    except Exception:
        text = resp.content.decode("utf-8", errors="ignore")
        return BeautifulSoup(text, "html.parser")


def _extract_cis_from_url(url: str) -> Optional[str]:
    m = re.search(r"/medicament/(\d+)/extrait", url)
    return m.group(1) if m else None


def _find_pdf_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    pdfs: set[str] = set()

    # 1) Cas fiable : onglet "Résumé des caractéristiques... et Notice"
    panel = soup.find(id="tabpanel-rcp-et-notice-panel")
    if panel:
        for a in panel.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            abs_url = urljoin(base_url, href)

            text = a.get_text(" ", strip=True).lower()

            # Lien "officiel" repéré dans ton HTML
            if "vers le rcp" in text or "rcp" in text or "notice" in text:
                pdfs.add(abs_url)

            # Si c'est un PDF direct (EMA ou autre)
            if abs_url.lower().endswith(".pdf"):
                pdfs.add(abs_url)

            # PDF mobile BDM (si jamais)
            if "base-donnees-publique.medicaments.gouv.fr/pdf/" in abs_url:
                pdfs.add(abs_url)

        if pdfs:
            return sorted(pdfs)

    # 2) Fallback : scan global (moins “sémantique”, mais pratique)
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        if abs_url.lower().endswith(".pdf") or "base-donnees-publique.medicaments.gouv.fr/pdf/" in abs_url:
            pdfs.add(abs_url)

    return sorted(pdfs)


def scrape_extrait(extrait_url: str, timeout_s: int = 25) -> Dict[str, Any]:
    """
    Scrape une page /medicament/<CIS>/extrait et récupère les liens PDF
    (BDM ou EMA). Ne touche PAS MongoDB.
    """
    r = requests.get(extrait_url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = _make_soup(r)

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = re.sub(r"\s+", " ", h1.get_text(strip=True)).strip()

    cis = _extract_cis_from_url(extrait_url)

    pdf_links = _find_pdf_links(soup, extrait_url)

    # petit hash pour détecter changement des liens
    content_hash = hashlib.md5(("|".join(pdf_links) + (title or "")).encode("utf-8")).hexdigest()

    return {
        "metadata": {
            "url": extrait_url,
            "cis": cis,
            "title": title,
            "content_hash": content_hash,
            "source": "bdpm_extrait",
        },
        "pdf_links": pdf_links,
    }
