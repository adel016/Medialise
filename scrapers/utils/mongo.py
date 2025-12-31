import os
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    # charge .env puis surcharge par .env.local si présent
    load_dotenv(".env")
    load_dotenv(".env.local", override=True)
except Exception:
    pass

def get_collection(name: str):
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "medsearch")

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]
    return db[name]
