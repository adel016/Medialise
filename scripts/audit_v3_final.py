import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

meds = db["medicines_v3"]
subs = db["substances_v3"]
market = db["medicine_market"]

def main():
    print("=== COUNTS ===")
    print("medicines_v3:", meds.count_documents({}))
    print("substances_v3:", subs.count_documents({}))
    print("medicine_market:", market.count_documents({}))
    print()

    print("=== medicines_v3.substance_ref_ids ===")
    print("no field:", meds.count_documents({"substance_ref_ids": {"$exists": False}}))
    print("empty:", meds.count_documents({"substance_ref_ids": {"$size": 0}}))
    print("non-empty:", meds.count_documents({"substance_ref_ids.0": {"$exists": True}}))

    sub_ids = set(subs.distinct("_id"))
    orphan = 0
    bad = 0
    for m in meds.find({"substance_ref_ids.0": {"$exists": True}}, {"substance_ref_ids": 1}):
        for sid in m.get("substance_ref_ids", []):
            if not isinstance(sid, ObjectId):
                bad += 1
                continue
            if sid not in sub_ids:
                orphan += 1
                break
    print("orphan medicines:", orphan)
    print("bad types:", bad)
    print()

    print("=== medicine_market.medicine_ref ===")
    print("ObjectId refs:", market.count_documents({"medicine_ref": {"$type": "objectId"}}))

    med_ids = set(meds.distinct("_id"))
    orphan_m = 0
    bad_m = 0
    for d in market.find({"medicine_ref": {"$exists": True}}, {"medicine_ref": 1}):
        mr = d.get("medicine_ref")
        if not isinstance(mr, ObjectId):
            bad_m += 1
            continue
        if mr not in med_ids:
            orphan_m += 1
    print("orphan market refs:", orphan_m)
    print("bad type market refs:", bad_m)

    print("\n=== DONE ===")

if __name__ == "__main__":
    main()
