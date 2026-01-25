import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

old = db["medicines"]
new = db["medicines_v3"]
mapc = db["medicine_id_map"]

new.drop()
mapc.drop()

inserted = 0
for m in old.find({}):
    old_id = m["_id"]            # string
    new_id = ObjectId()

    m2 = dict(m)
    m2["_id"] = new_id
    m2["legacy"] = {"medicine_id": old_id}
    # garde ton ID historique aussi en top-level si tu veux :
    m2["medicine_key"] = old_id

    new.insert_one(m2)
    mapc.insert_one({"_id": old_id, "new_id": new_id})
    inserted += 1

print("created medicines_v3:", inserted)
print("created medicine_id_map:", mapc.count_documents({}))
