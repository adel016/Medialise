# scrapers/import_json_to_mongo.py
import glob
import json
import os
from scrapers.utils.mongo import get_collection


def _ensure_url_top_level(data: dict) -> tuple[dict, str | None]:
    """
    Garantit data["url"] à partir de data["metadata"]["url"].
    Retourne (data, url).
    """
    meta = data.get("metadata") or {}
    url = meta.get("url")
    if isinstance(url, str) and url and not data.get("url"):
        data["url"] = url
    return data, url


def _ensure_schema_version(data: dict) -> dict:
    data.setdefault("schema_version", 2)
    return data


def _merge_source(data: dict) -> dict:
    """
    Assure que data["source"] est un dict si présent, sinon le crée.
    Ne devine rien (pas de if URL).
    """
    src = data.get("source")
    if src is None:
        data["source"] = {}
    elif not isinstance(src, dict):
        # si jamais un scraper met un mauvais type, on remplace par dict vide
        data["source"] = {}
    return data


def normalize_for_mongo(data: dict) -> tuple[dict, str | None]:
    """
    Normalisation minimale et sûre:
    - url top-level cohérent
    - source dict
    - schema_version
    """
    if not isinstance(data, dict):
        return data, None

    data, url = _ensure_url_top_level(data)
    data = _merge_source(data)
    data = _ensure_schema_version(data)
    return data, url


def import_single_file(path: str):
    medicines = get_collection("medicines")

    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    count = 0
    for entry in entries:
        if entry.get("status") != "success":
            continue

        data = entry.get("data") or {}
        if not isinstance(data, dict):
            continue

        data, url = normalize_for_mongo(data)
        if not url:
            continue

        medicines.update_one(
            {"url": url},
            {"$set": data},
            upsert=True
        )
        count += 1

    print(f"[{os.path.basename(path)}] {count} documents importés")


def import_all_from_test_outputs():
    base_dir = os.path.dirname(__file__)
    pattern = os.path.join(base_dir, "test_outputs", "agno_test_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print("Aucun fichier JSON trouvé dans scrapers/test_outputs")
        return

    print(f"{len(files)} fichiers trouvés.")
    for path in files:
        import_single_file(path)


def upsert_document(data: dict) -> int:
    """
    Upsert via metadata.url (clé stable).
    Le pipeline doit injecter le contexte 'source' (country/authority/...) en amont.
    """
    medicines = get_collection("medicines")

    data, url = normalize_for_mongo(data)
    if not url:
        return 0

    medicines.update_one(
        {"url": url},
        {"$set": data},
        upsert=True
    )
    return 1


if __name__ == "__main__":
    import_all_from_test_outputs()
