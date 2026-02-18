#!/usr/bin/env python3
"""Script pour examiner la structure des documents et les sources"""

from pymongo import MongoClient

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    print("Exemples de documents medicine_market:")
    print("=" * 80)
    
    # Document BDPM
    doc_bdpm = db.medicine_market.find_one({'market_key': {'$regex': 'BDPM'}})
    if doc_bdpm:
        print("\n1. Document BDPM:")
        print(f"   _id: {doc_bdpm.get('_id')}")
        print(f"   market_key: {doc_bdpm.get('market_key')}")
        print(f"   brand_title: {doc_bdpm.get('brand_title')}")
        print(f"   country: {doc_bdpm.get('country')}")
    
    # Document non-BDPM
    doc_other = db.medicine_market.find_one({'market_key': {'$not': {'$regex': 'BDPM'}}})
    if doc_other:
        print("\n2. Document autre:")
        print(f"   _id: {doc_other.get('_id')}")
        print(f"   market_key: {doc_other.get('market_key')}")
        print(f"   brand_title: {doc_other.get('brand_title')}")
        print(f"   country: {doc_other.get('country')}")
    
    # Regarder s'il y a une collection séparée pour les autres sources
    print("\n\nCollections disponibles:")
    print("=" * 80)
    collections = db.list_collection_names()
    for coll in collections:
        count = db[coll].count_documents({})
        print(f"  - {coll}: {count} documents")
    
    # Vérifier si drugbank, etc. sont dans d'autres collections
    print("\n\nRecherche de données DrugBank, OpenFDA, etc.:")
    print("=" * 80)
    
    # Chercher DrugBank
    drugbank_docs = db.medicines.count_documents({'source': {'$regex': 'drugbank', '$options': 'i'}})
    print(f"  - DrugBank dans medicines: {drugbank_docs}")
    
    # Chercher OpenFDA
    openfda_docs = db.medicines.count_documents({'source': {'$regex': 'openfda', '$options': 'i'}})
    print(f"  - OpenFDA dans medicines: {openfda_docs}")
    
    # Chercher PubChem
    pubchem_docs = db.medicines.count_documents({'source': {'$regex': 'pubchem', '$options': 'i'}})
    print(f"  - PubChem dans medicines: {pubchem_docs}")
    
    # Regarder un exemple de document dans medicines
    print("\n\nExemple de document dans 'medicines':")
    print("=" * 80)
    sample_med = db.medicines.find_one()
    if sample_med:
        print(f"   _id: {sample_med.get('_id')}")
        print(f"   title: {sample_med.get('title')}")
        print(f"   source: {sample_med.get('source')}")
        print(f"   url: {sample_med.get('url')}")
        print(f"   Clés disponibles: {list(sample_med.keys())[:15]}")

if __name__ == '__main__':
    main()
