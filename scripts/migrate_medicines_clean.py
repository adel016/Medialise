import os
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from pymongo import MongoClient, UpdateOne


# =========================
# CONFIG
# =========================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "medicsearch"
COLL_NAME = "medicines"

# Mets DRY_RUN = True pour tester sans écrire en base
DRY_RUN = False

BATCH_SIZE = 500


# =========================
# HELPERS
# =========================
def parse_ddmmyyyy(date_str: Optional[str]) -> Optional[datetime]:
    """Convertit 'DD/MM/YYYY' -> datetime UTC. Retourne None si invalide."""
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", date_str)
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return datetime(y, mo, d, tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_source_from_url(url: Optional[str]) -> Dict[str, Any]:
    """
    Ex: https://.../affichageDoc.php?specid=61266250&typedoc=R
    -> specid:int, type_doc:str
    """
    out = {"site": "bdpm", "url": url}
    if not url or not isinstance(url, str):
        return out

    specid = None
    typedoc = None

    m1 = re.search(r"[?&]specid=(\d+)", url)
    if m1:
        specid = int(m1.group(1))

    m2 = re.search(r"[?&]typedoc=([A-Za-z])", url)
    if m2:
        typedoc = m2.group(1).upper()

    if specid is not None:
        out["specid"] = specid
    if typedoc is not None:
        out["type_doc"] = typedoc

    return out


def normalize_strengths(values):
    """Nettoyage léger: '200 000 UI' -> '200000 UI' (optionnel)."""
    if not isinstance(values, list):
        return []
    cleaned = []
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        s = re.sub(r"\s+", " ", s)
        # enlève espaces au milieu des nombres: "200 000 UI" -> "200000 UI"
        s = re.sub(r"(\d)\s+(\d)", r"\1\2", s)
        cleaned.append(s)
    # unique en gardant l'ordre
    seen = set()
    out = []
    for x in cleaned:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_drug(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Construit drug.* depuis medicine_details + title.
    """
    md = doc.get("medicine_details") or {}
    title = doc.get("title") or ""

    drug = {}

    # Champs depuis medicine_details
    lab = md.get("laboratoire")
    if isinstance(lab, str) and lab.strip():
        drug["laboratory"] = lab.strip()

    form = md.get("forme")
    if isinstance(form, str) and form.strip():
        drug["form"] = form.strip()

    subs = md.get("substances_actives")
    if isinstance(subs, list):
        drug["active_substances"] = [s.strip() for s in subs if isinstance(s, str) and s.strip()]

    strengths = md.get("dosages") or md.get("dosage") or []
    drug["strengths"] = normalize_strengths(strengths)

    # Name: on essaie d'utiliser le title, sinon vide
    if isinstance(title, str) and title.strip():
        drug["full_title"] = title.strip()

        # Tentative simple: split "..., forme"
        # "A 313 200 000 UI POUR CENT, pommade" => name="A 313 200 000 UI POUR CENT"
        parts = [p.strip() for p in title.split(",") if p.strip()]
        if parts:
            drug["name"] = parts[0]

            # si form absent, on prend la 2e partie
            if "form" not in drug and len(parts) >= 2:
                drug["form"] = parts[1].capitalize()

    return drug


def add_section_codes(sections):
    """
    Ajoute un 'code' basé sur le début du titre :
    '4.1. Indications...' -> code='4.1'
    '1. DENOMINATION...' -> code='1'
    """
    if not isinstance(sections, list):
        return sections

    out = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        title = sec.get("title", "")
        code = None
        if isinstance(title, str):
            t = title.strip()
            m = re.match(r"^(\d+(?:\.\d+)*)", t)
            if m:
                code = m.group(1)

        # on renomme content -> blocks + formatting -> style (sans tout casser)
        content = sec.get("content", [])
        blocks = []
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                block = {"text": b.get("text", "")}
                fmt = b.get("formatting") or {}
                if isinstance(fmt, dict):
                    style = {}
                    # ne garde que l'essentiel
                    for k_src, k_dst in [
                        ("bold", "bold"),
                        ("italic", "italic"),
                        ("underline", "underline"),
                        ("list_type", "list"),
                        ("alignment", "align"),
                    ]:
                        val = fmt.get(k_src)
                        if val is not None and val != "" and val != "none":
                            style[k_dst] = val
                    if style:
                        block["style"] = style
                blocks.append(block)

        new_sec = {
            "title": title,
            "blocks": blocks,
            "subsections": sec.get("subsections", []),
        }
        if code:
            new_sec["code"] = code

        out.append(new_sec)

    return out


# =========================
# MIGRATION
# =========================
def build_update(doc: Dict[str, Any]) -> Optional[UpdateOne]:
    url = doc.get("url")
    source = parse_source_from_url(url)

    drug = extract_drug(doc)

    updated_at = parse_ddmmyyyy(doc.get("update_date"))
    scraped_at = doc.get("last_scraped")  # déjà un Date BSON normalement
    content_hash = doc.get("content_hash")

    # sections -> rcp.sections
    sections = doc.get("sections", [])
    rcp_sections = add_section_codes(sections)

    set_doc = {
        "source": source,
        "drug": drug,
        "document": {
            "updated_at": updated_at,
            "scraped_at": scraped_at,
            "content_hash": content_hash,
        },
        "rcp": {
            "sections": rcp_sections,
        },
        # marqueur pour savoir que c'est migré
        "schema_version": 2,
    }

    # enlève les None pour éviter de créer des champs inutiles
    if set_doc["document"]["updated_at"] is None:
        del set_doc["document"]["updated_at"]
    if set_doc["document"]["scraped_at"] is None:
        del set_doc["document"]["scraped_at"]
    if set_doc["document"]["content_hash"] is None:
        del set_doc["document"]["content_hash"]

    unset_doc = {
        "metadata": "",
        "medicine_details": "",
        "update_date": "",
        "sections": "",
        # optionnel : si tu veux supprimer title aussi (je conseille oui)
        "title": "",
        # et content_hash / last_scraped si tu veux les garder uniquement dans document.*
        "content_hash": "",
        "last_scraped": "",
    }

    return UpdateOne(
        {"_id": doc["_id"]},
        {
            "$set": set_doc,
            "$unset": unset_doc,
        }
    )


def main():
    client = MongoClient(MONGO_URI)
    coll = client[DB_NAME][COLL_NAME]

    # On ne migre que ceux pas encore en v2
    cursor = coll.find(
        {"schema_version": {"$ne": 2}},
        projection={"_id": 1, "url": 1, "title": 1, "medicine_details": 1, "update_date": 1,
                    "last_scraped": 1, "sections": 1, "content_hash": 1}
    )

    ops = []
    total = 0

    for doc in cursor:
        op = build_update(doc)
        if op:
            ops.append(op)

        if len(ops) >= BATCH_SIZE:
            total += len(ops)
            if DRY_RUN:
                print(f"[DRY_RUN] batch prêt: {len(ops)} (total simulé={total})")
            else:
                res = coll.bulk_write(ops, ordered=False)
                print(f"[WRITE] matched={res.matched_count} modified={res.modified_count}")
            ops = []

    if ops:
        total += len(ops)
        if DRY_RUN:
            print(f"[DRY_RUN] batch prêt: {len(ops)} (total simulé={total})")
        else:
            res = coll.bulk_write(ops, ordered=False)
            print(f"[WRITE] matched={res.matched_count} modified={res.modified_count}")

    print("Terminé.")


if __name__ == "__main__":
    main()
