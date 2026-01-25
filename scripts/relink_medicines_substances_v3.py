import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

meds = db["medicines"]
mapc = db["substance_id_map"]

# Build mapping old_string_id -> ObjectId
m = {d["_id"]: d["new_id"] for d in mapc.find({}, {"new_id": 1})}

# PROOF: take 1 medicine and update it, printing matched/modified
one = meds.find_one({}, {"_id": 1, "substance_labels": 1})
print("sample medicine _id:", one["_id"])

labels = one.get("substance_labels") or []
ids = []
for lab in labels:
    nid = m.get(lab)
    if isinstance(nid, ObjectId):
        ids.append(nid)

# uniq
seen = set()
uniq = []
for x in ids:
    if x not in seen:
        seen.add(x)
        uniq.append(x)

res = meds.update_one({"_id": one["_id"]}, {"$set": {"substance_ref_ids": uniq}})
print("PROOF update_one matched:", res.matched_count, "modified:", res.modified_count)
print("PROOF written array length:", len(uniq))

# Verify immediately
check = meds.find_one({"_id": one["_id"]}, {"_id": 0, "substance_ref_ids": 1})
print("PROOF readback:", check)

# Now do full pass
updated = 0
missing = 0
total = 0

cur = meds.find({}, {"_id": 1, "substance_labels": 1})
for doc in cur:
    labels = doc.get("substance_labels") or []
    ids = []
    for lab in labels:
        if not isinstance(lab, str):
            continue
        total += 1
        nid = m.get(lab)
        if isinstance(nid, ObjectId):
            ids.append(nid)
        else:
            missing += 1

    seen = set()
    uniq = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            uniq.append(x)

    r = meds.update_one({"_id": doc["_id"]}, {"$set": {"substance_ref_ids": uniq}})
    if r.matched_count == 1:
        updated += 1

print("medicines updated:", updated)
print("labels processed:", total)
print("missing mapping:", missing)

print("FINAL check exists:", meds.count_documents({"substance_ref_ids": {"$exists": True}}))
print("FINAL check has at least one:", meds.count_documents({"substance_ref_ids.0": {"$exists": True}}))
