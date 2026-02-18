#!/usr/bin/env python3
"""
Script pour lister les collections et voir leur contenu
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient
import time

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "medicsearch"  # La vraie base de données

def list_collections():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Test de connexion
        client.admin.command('ping')
        print("✓ Connexion MongoDB réussie")
    except Exception as e:
        print(f"✗ Erreur de connexion MongoDB: {e}")
        return
    
    db = client[DB_NAME]
    
    print("=" * 80)
    print(f"COLLECTIONS DANS {DB_NAME}")
    print("=" * 80)
    
    collections = db.list_collection_names()
    
    for coll_name in sorted(collections):
        count = db[coll_name].count_documents({})
        print(f"\n{coll_name}: {count} documents")
        
        # Afficher un exemple de document
        sample = db[coll_name].find_one()
        if sample:
            print(f"  Clés du premier document:")
            for key in sorted(sample.keys())[:10]:
                value = sample[key]
                if isinstance(value, str):
                    value_str = value[:50] if len(value) > 50 else value
                else:
                    value_str = str(value)[:50]
                print(f"    - {key}: {value_str}")

if __name__ == "__main__":
    try:
        list_collections()
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
