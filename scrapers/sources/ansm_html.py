"""
Scraper HTML pour les RCP ANSM.

Ce module est HTML-only (aucun accès MongoDB).
Il expose une fonction principale :

    scrape_html(url: str) -> dict

qui retourne une structure à deux niveaux :

{
    "metadata": {
        "url": ...,
        "title": ...,
        "update_date": ...,
        "medicine_details": {
            "substances_actives": [...],
            "dosages": [...],
            "laboratoire": "...",
            "forme": "..."
        },
        "content_hash": "..."
    },
    "sections": [...]   # hiérarchie des sections du RCP
}
"""

import re
import hashlib
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Utilitaire interne : création du BeautifulSoup robuste
# ---------------------------------------------------------------------------

def _make_soup_from_response(response: requests.Response) -> BeautifulSoup:
    """
    Essaie de construire un BeautifulSoup en gérant plusieurs encodages possibles.
    """
    # Première tentative directe
    try:
        return BeautifulSoup(response.content, "html.parser")
    except Exception:
        pass

    # Tentatives avec encodages alternatifs
    for encoding in ["utf-8", "latin-1", "windows-1252", "iso-8859-1"]:
        try:
            text = response.content.decode(encoding, errors="ignore")
            return BeautifulSoup(text, "html.parser")
        except Exception:
            continue

    # Dernier recours : parser quand même le binaire brut
    return BeautifulSoup(response.content, "html.parser")


# ---------------------------------------------------------------------------
# Fonctions d'extraction principales
# (reprennent ta logique existante, légèrement structurée)
# ---------------------------------------------------------------------------

def extract_sections(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Construit une hiérarchie des sections à partir de <a name="RcpDenomination">.
    Si non trouvé, commence après <p class="DateNotif">.
    L'extraction s'arrête à <a name="RcpInstPrepRadioph">.
    """
    root_sections: List[Dict[str, Any]] = []    # Liste des sections principales
    stack: List[Dict[str, Any]] = []           # Pile pour gérer la hiérarchie
    processed_elements = set()                 # Pour suivre les éléments déjà traités

    body = soup.find("body")
    if not body:
        return root_sections

    # Trouver le point de départ
    start_found = False
    elements = body.find_all(["a", "p", "div", "table"], recursive=True)

    for element in elements:
        # Point de départ principal : RcpDenomination
        if element.name == "a" and element.get("name") == "RcpDenomination":
            start_found = True
            continue
        # Point de départ alternatif : après DateNotif
        elif (
            not start_found
            and element.name == "p"
            and element.has_attr("class")
            and "DateNotif" in element["class"]
        ):
            start_found = True
            continue

        # Ne rien traiter avant le point de départ
        if not start_found:
            continue

        # Arrêter à l'ancre de fin
        if element.name == "a" and element.get("name") == "RcpInstPrepRadioph":
            break

        # Ne pas traiter les éléments déjà traités
        if element in processed_elements:
            continue

        # Détecter un titre de section
        if element.name == "p" and element.has_attr("class"):
            section_class = next(
                (cls for cls in element["class"] if cls.startswith("AmmAnnexeTitre")),
                None,
            )
            if section_class:
                match = re.search(r"AmmAnnexeTitre(\d+)(Bis)?", section_class)
                if match:
                    level = int(match.group(1))
                    a_tag = element.find("a")
                    title = (
                        a_tag.get_text(strip=True)
                        if a_tag
                        else element.get_text(strip=True)
                    )

                    # Créer la nouvelle section (level seulement interne)
                    new_section: Dict[str, Any] = {
                        "title": title,
                        "content": [],
                        "subsections": [],
                        "level": level,  # pour la pile uniquement
                    }

                    # Gérer la hiérarchie
                    while stack and stack[-1].get("level", 0) >= level:
                        stack.pop()
                    if stack:
                        stack[-1]["subsections"].append(new_section)
                    else:
                        root_sections.append(new_section)
                    stack.append(new_section)
                    continue

        # Traiter le contenu
        content_data: Dict[str, Any]

        if element.name == "table":
            # Extraction du contenu de tableau
            try:
                rows = element.find_all("tr")

                # Marquer tous les éléments du tableau comme traités
                for row in rows:
                    for cell in row.find_all(["td", "th"]):
                        processed_elements.add(cell)
                        for child in cell.find_all(True):
                            processed_elements.add(child)

                headers: List[str] = []
                header_row = element.find("thead")
                if header_row and header_row.find_all("th"):
                    headers = [
                        th.get_text(strip=True) for th in header_row.find_all("th")
                    ]

                table_data: List[List[str]] = []
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    row_data = [col.get_text(strip=True) for col in cols]
                    if any(cell.strip() for cell in row_data):
                        table_data.append(row_data)

                content_data = {"table": table_data}
                if headers:
                    content_data["headers"] = headers

                caption = element.find("caption")
                if caption:
                    content_data["caption"] = caption.get_text(strip=True)
                    processed_elements.add(caption)
            except Exception as e:
                content_data = {
                    "error": f"Erreur d'extraction de tableau: {str(e)}"
                }

        elif element.name in ["p", "div"]:
            # Ne pas re-traiter les titres de section
            if (
                element.has_attr("class")
                and any(cls.startswith("AmmAnnexeTitre") for cls in element["class"])
            ):
                continue
            content_data = extract_text_content(element)
        else:
            continue

        # Ajouter le contenu à la dernière section active
        if stack:
            stack[-1]["content"].append(content_data)
        elif root_sections:
            root_sections[-1]["content"].append(content_data)
        else:
            # Cas où du contenu apparaît avant toute section détectée
            root_sections.append(
                {
                    "title": "Contenu non sectionné",
                    "content": [content_data],
                    "subsections": [],
                    "level": 0,
                }
            )

    # Nettoyer les sections en supprimant le champ "level"
    def _clean_sections(sections: List[Dict[str, Any]]) -> None:
        for section in sections:
            if "level" in section:
                del section["level"]
            _clean_sections(section["subsections"])

    _clean_sections(root_sections)
    return root_sections


def extract_medicine_title(soup: BeautifulSoup) -> str:
    """Extrait directement le titre du médicament"""
    denomination_section = soup.find("a", {"name": "RcpDenomination"})
    if denomination_section:
        title_element = denomination_section.find_next(
            "p",
            class_=lambda c: c
            and ("AmmCorpsTexteGras" in c or "AmmDenomination" in c),
        )
        if title_element:
            return re.sub(r"\s+", " ", title_element.get_text(strip=True)).strip()

    # Méthodes alternatives
    title_h1 = soup.find("h1", class_="textedeno")
    if title_h1:
        title_text = title_h1.get_text(strip=True)
        if " - " in title_text:
            title_text = title_text.split(" - ")[0].strip()
        return title_text

    # Dernière tentative
    for class_name in ["AmmDenomination", "AmmCorpsTexteGras"]:
        title_elements = soup.find_all("p", class_=class_name, limit=3)
        for element in title_elements:
            text = element.get_text(strip=True)
            if text and len(text) > 5:
                return re.sub(r"\s+", " ", text).strip()

    return "Document sans titre"


def extract_update_date(soup: BeautifulSoup) -> str:
    """Extrait la date de mise à jour du document"""
    update_date = "Date not found"
    ansm_date_pattern = soup.find(
        string=lambda text: text and "ANSM - Mis à jour le :" in text
    )

    if ansm_date_pattern:
        update_date = ansm_date_pattern.split("ANSM - Mis à jour le :")[1].strip()
    else:
        update_date_element = soup.find("div", id="menuhaut")
        if update_date_element:
            update_date = update_date_element.get_text(strip=True)
            if "mise à jour" in update_date:
                update_date = update_date.split("mise à jour")[1].strip()
            elif "mise" in update_date:
                update_date = update_date.split("mise")[1].strip()

    return update_date.replace("le ", "").strip()


def extract_laboratory(soup: BeautifulSoup) -> str:
    """Extrait directement le laboratoire"""
    titulaire_section = soup.find("a", {"name": "RcpTitulaireAmm"})
    if titulaire_section:
        paragraphs = []
        current_elem = titulaire_section.parent

        # Obtenir quelques paragraphes après l'ancre
        for _ in range(5):
            current_elem = current_elem.find_next(["p", "div"])
            if not current_elem:
                break
            paragraphs.append(current_elem)

        # Stratégie 1: span class="gras"
        for paragraph in paragraphs:
            spans = paragraph.find_all("span", class_="gras")
            for span in spans:
                text = span.get_text(strip=True)
                if (
                    text
                    and not re.match(r"^\d{5}", text)
                    and not re.search(r"\d{5}\s", text)
                ):
                    return text

        # Stratégie 2: paragraphe en gras
        for paragraph in paragraphs:
            if (
                paragraph.has_attr("class")
                and "AmmCorpsTexteGras" in paragraph["class"]
            ) or paragraph.find("span", class_="gras"):
                text = paragraph.get_text(strip=True)
                if not text.startswith(("7.", "8.", "TITULAIRE", "DATE")) and not re.match(
                    r"^\d{5}", text
                ):
                    return text

        # Stratégie 3: premier paragraphe non vide qui n'est pas une adresse
        for paragraph in paragraphs:
            text = paragraph.get_text(strip=True)
            if (
                text
                and not text.startswith(("7.", "8.", "TITULAIRE", "DATE"))
                and not re.match(r"^\d{5}", text)
                and not re.search(r"\b\d{5}\b", text)
                and not any(
                    word.lower() in text.lower()
                    for word in ["rue", "avenue", "boulevard", "cedex"]
                )
            ):
                return text.replace("LABORATOIRES", "LABORATOIRES ").strip()

    return ""


def extract_substances_and_dosages(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Extrait la première substance active et son dosage à partir du premier élément
    avec la classe 'AmmComposition'.
    """
    dosages: List[str] = []
    substances: List[str] = []

    paragraph = soup.find("p", class_="AmmComposition")

    if paragraph:
        text = paragraph.get_text(strip=True)

        match = re.search(
            r"^(.*?)\.{3,}\s*([\d\s,]+(?:[.,]\d+)?\s*(?:mg|g|ml|µg|UI|U\.I\.|microgrammes|unités|%))\s*$",
            text,
            re.UNICODE | re.IGNORECASE,
        )
        if match:
            substance = match.group(1).strip()
            dosage = match.group(2).strip()

            # Nettoyage du nom de la substance : supprime les contenus entre parenthèses
            substance = re.sub(r"\s*\([^)]*\)", "", substance).strip()

            substances.append(substance)
            dosages.append(dosage)

    return {
        "substances_actives": substances,
        "dosages": dosages,
    }


def extract_pharmaceutical_form(soup: BeautifulSoup) -> str:
    """Extrait la forme pharmaceutique"""
    form_section = soup.find("a", {"name": "RcpFormePharm"})
    if form_section:
        form_paragraph = form_section.find_next("p")
        if form_paragraph:
            return form_paragraph.get_text(strip=True).rstrip(".")

    # Alternative via le titre
    title = extract_medicine_title(soup)
    if title and "," in title:
        return title.split(",", 1)[1].strip()

    return ""


def extract_text_content(element) -> Dict[str, Any]:
    """Extrait le texte et les attributs de formatage importants"""
    text = re.sub(r"\s+", " ", element.get_text(strip=False)).strip()

    formatting = {
        "bold": False,
        "italic": False,
        "underline": False,
        "list_type": None,
        "alignment": "left",
    }

    # Détection de formatage
    if element.name in ["strong", "b"] or element.find(["strong", "b"]):
        formatting["bold"] = True

    if element.name in ["em", "i"] or element.find(["em", "i"]):
        formatting["italic"] = True

    if "class" in element.attrs:
        classes = " ".join(element["class"])
        if "gras" in classes or "AmmCorpsTexteGras" in classes:
            formatting["bold"] = True
        if "italique" in classes:
            formatting["italic"] = True
        if "souligne" in classes:
            formatting["underline"] = True
        if "AmmListePuces" in classes:
            formatting["list_type"] = "bullet"
        style = (element.get("style") or "").lower()
        if "center" in classes or "text-align:center" in style:
            formatting["alignment"] = "center"

    if element.name == "li" or (element.parent and element.parent.name in ["ul", "ol"]):
        formatting["list_type"] = (
            "bullet" if element.parent and element.parent.name == "ul" else "numbered"
        )

    return {"text": text, "formatting": formatting}


def generate_content_hash(document: Dict[str, Any]) -> str:
    """Génère un hash du contenu essentiel pour détecter les changements"""
    content_string = (
        document.get("title", "")
        + str(document.get("update_date", ""))
        + str(document.get("medicine_details", {}))
        + str(
            [
                {k: v for k, v in section.items() if k != "subsections"}
                for section in document.get("sections", [])
            ]
        )
    )
    return hashlib.md5(content_string.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Fonction principale utilisée par Agno / autres pipelines
# ---------------------------------------------------------------------------

def scrape_html(url: str) -> Dict[str, Any]:
    """
    Scrape une page RCP HTML ANSM et retourne une structure à deux niveaux :

    {
        "metadata": {
            "url": ...,
            "title": ...,
            "update_date": ...,
            "medicine_details": {...},
            "content_hash": "..."
        },
        "sections": [...]
    }

    Cette fonction ne touche PAS à la base MongoDB.
    Elle peut être utilisée dans Agno, dans des scripts batch, etc.
    """
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    soup = _make_soup_from_response(response)

    # Extraction des champs principaux
    title = extract_medicine_title(soup)
    substances_dosages = extract_substances_and_dosages(soup)
    update_date = extract_update_date(soup)
    laboratoire = extract_laboratory(soup)
    forme = extract_pharmaceutical_form(soup)

    sections = extract_sections(soup)

    metadata: Dict[str, Any] = {
        "url": url,
        "title": title,
        "update_date": update_date,
        "medicine_details": {
            "substances_actives": substances_dosages["substances_actives"],
            "dosages": substances_dosages["dosages"],
            "laboratoire": laboratoire,
            "forme": forme,
        },
    }

    # Pour réutiliser ta logique de hash
    document_for_hash = {
        "title": metadata["title"],
        "update_date": metadata["update_date"],
        "medicine_details": metadata["medicine_details"],
        "sections": sections,
    }
    metadata["content_hash"] = generate_content_hash(document_for_hash)

    return {
        "metadata": metadata,
        "sections": sections,
    }
