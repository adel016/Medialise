import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

market = db["medicine_market"]
mapc = db["medicine_id_map"]  # _id = old string key, new_id = ObjectId

m = {d["_id"]: d["new_id"] for d in mapc.find({}, {"new_id": 1})}

# PROOF: use medicine_id (string) as join key
one = market.find_one({}, {"_id": 1, "medicine_id": 1, "medicine_ref": 1})
print("sample market medicine_id:", one.get("medicine_id"))
print("current medicine_ref:", one.get("medicine_ref"))

key = one.get("medicine_id")
nid = m.get(key)
print("PROOF resolved new ObjectId from medicine_id:", nid)

if isinstance(nid, ObjectId):
    r = market.update_one({"_id": one["_id"]}, {"$set": {"medicine_ref": nid}})
    print("PROOF update_one matched:", r.matched_count, "modified:", r.modified_count)
    print("PROOF readback:", market.find_one({"_id": one["_id"]}, {"_id": 0, "medicine_ref": 1}))

matched = 0
unmatched = 0

cur = market.find({"medicine_id": {"$type": "string", "$gt": ""}}, {"_id": 1, "medicine_id": 1})
for doc in cur:
    nid = m.get(doc["medicine_id"])
    if isinstance(nid, ObjectId):
        market.update_one({"_id": doc["_id"]}, {"$set": {"medicine_ref": nid}})
        matched += 1
    else:
        unmatched += 1

print("matched market docs:", matched)
print("unmatched market docs:", unmatched)
print("FINAL market with ObjectId medicine_ref:", market.count_documents({'medicine_ref': {'$type': 'objectId'}}))
