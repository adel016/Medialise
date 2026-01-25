import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

def _get_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI_HOST") or "mongodb://localhost:27017"
    dbname = os.getenv("MONGO_DB") or "medicsearch"
    return MongoClient(uri)[dbname]

# alias centralisé
COLLECTION_ALIASES_V3 = {
    "medicines": "medicines_v3",
    "substances": "substances_v3",
    "medicine_market": "medicine_market",
}

def get_collection(name: str):
    """
    Centralise le mapping des collections.
    Par défaut on travaille en V3.
    Si MEDICSEARCH_LEGACY=1, alors pas d'alias (retourne le nom demandé).
    """
    db = _get_db()
    legacy = os.getenv("MEDICSEARCH_LEGACY", "0") == "1"
    if legacy:
        return db[name]
    return db[COLLECTION_ALIASES_V3.get(name, name)]
