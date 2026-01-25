import os
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

def ensure(coll, keys, name, unique=False):
    names = {i["name"] for i in coll.list_indexes()}
    if name in names:
        print("= exists", coll.name, name)
        return
    coll.create_index(keys, name=name, unique=unique)
    print("+ created", coll.name, name)

def main():
    meds = db["medicines_v3"]
    subs = db["substances_v3"]
    market = db["medicine_market"]

    ensure(meds, [("schema_version", ASCENDING)], "schema_version_1")
    ensure(meds, [("inns", ASCENDING)], "inns_1")                     # multikey
    ensure(meds, [("substance_ref_ids", ASCENDING)], "substance_ref_ids_1")  # multikey
    ensure(meds, [("medicine_key", ASCENDING)], "medicine_key_1", unique=True)  # old id unique

    ensure(subs, [("label_normalized", ASCENDING)], "label_normalized_1")
    ensure(subs, [("legacy.substances_id", ASCENDING)], "legacy_substances_id_1", unique=True)

    ensure(market, [("medicine_ref", ASCENDING)], "medicine_ref_1")
    ensure(market, [("country", ASCENDING), ("cis", ASCENDING)], "country_1_cis_1")

if __name__ == "__main__":
    main()
