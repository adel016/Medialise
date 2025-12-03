import glob
import json
import os
from scrapers.utils.mongo import get_collection

def import_single_file(path: str):
    medicines = get_collection("medicines")

    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    count = 0
    for entry in entries:
        if entry.get("status") != "success":
            continue
        data = entry["data"]
        meta = data.get("metadata", {})
        url = meta.get("url")
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

if __name__ == "__main__":
    import_all_from_test_outputs()