import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

old = db["substances"]
new = db["substances_v3"]
mapc = db["substance_id_map"]  # mapping collection

new.drop()
mapc.drop()

inserted = 0

for s in old.find({}, {"label":1, "label_normalized":1, "created_at":1, "updated_at":1}):
    old_id = s["_id"]  # string
    new_id = ObjectId()

    new_doc = {
        "_id": new_id,
        "label": s.get("label"),
        "label_normalized": s.get("label_normalized"),
        "created_at": s.get("created_at"),
        "updated_at": s.get("updated_at"),
        "legacy": {"substances_id": old_id},
    }
    new.insert_one(new_doc)
    mapc.insert_one({"_id": old_id, "new_id": new_id})
    inserted += 1

print("created substances_v3:", inserted)
print("created substance_id_map:", mapc.count_documents({}))
