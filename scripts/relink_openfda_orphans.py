from dotenv import load_dotenv
load_dotenv()

from scrapers.utils.mongo import get_collection
from scrapers.sources.openfda_ndc import resolve_medicine_ref

def main(limit=2000):
    market = get_collection("medicine_market")
    meds = get_collection("medicines_v3")  # si chez toi c'est "medicines", change ici

    q = {"sources.openfda.endpoint": "drug/ndc", "medicine_ref": {"$exists": False}}
    cur = market.find(q, {"_id": 1, "sources.openfda.generic_name": 1, "sources.openfda.brand_name": 1}).limit(limit)

    updated = 0
    scanned = 0

    for doc in cur:
        scanned += 1
        src = (doc.get("sources") or {}).get("openfda") or {}
        mid = resolve_medicine_ref(
            meds,
            generic_name=src.get("generic_name"),
            brand_name=src.get("brand_name"),
        )
        if mid:
            market.update_one({"_id": doc["_id"]}, {"$set": {"medicine_ref": mid}})
            updated += 1

        if scanned % 200 == 0:
            print(f"[RELINK] scanned={scanned} updated={updated}")

    print(f"[RELINK] DONE scanned={scanned} updated={updated}")

if __name__ == "__main__":
    main()
