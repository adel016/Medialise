import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Charge les variables d'environnement depuis un .env éventuel
load_dotenv()

def get_mongo_client() -> MongoClient:
    """
    Retourne un client MongoDB.
    - En Docker, utilise par défaut mongodb://mongo:27017/
    - En local, tu peux surcharger via MONGO_URI dans le .env
    Exemple .env :
        MONGO_URI=mongodb://localhost:27017/
        MONGO_DB=medicsearch
    """
    mongo_uri = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
    return MongoClient(mongo_uri)

def get_db():
    """
    Retourne la base MongoDB définie par MONGO_DB (défaut : 'medicsearch').
    """
    db_name = os.getenv("MONGO_DB", "medicsearch")
    client = get_mongo_client()
    return client[db_name]

def get_collection(name: str):
    """
    Retourne une collection de la base MONGO_DB.
    """
    db = get_db()
    return db[name]