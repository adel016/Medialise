#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test pour vérifier l'adaptation V3 de medicine_details
"""
import sys
import os

# Forcer l'encodage UTF-8 pour Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient
from bson.objectid import ObjectId
import json

# Configuration MongoDB
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "medicsearch"  # La vraie base de données

def test_v3_structure():
    """Test de la structure V3 et des relations entre collections"""
    print("=" * 80)
    print("TEST DE LA STRUCTURE V3")
    print("=" * 80)
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Test 1: Vérifier l'existence des collections
    print("\n1. Vérification des collections...")
    collections = db.list_collection_names()
    required_collections = ["medicine_market", "medicines_v3", "substances_v3"]
    
    for coll in required_collections:
        if coll in collections:
            count = db[coll].count_documents({})
            print(f"   ✓ {coll}: {count} documents")
        else:
            print(f"   ✗ {coll}: MANQUANTE")
    
    # Test 2: Vérifier un document medicine_market
    print("\n2. Test d'un document medicine_market...")
    market_doc = db.medicine_market.find_one()
    
    if market_doc:
        print(f"   ✓ Document trouvé: {market_doc['_id']}")
        print(f"   - brand_title: {market_doc.get('brand_title')}")
        print(f"   - cis: {market_doc.get('cis')}")
        print(f"   - form: {market_doc.get('form')}")
        print(f"   - laboratory: {market_doc.get('laboratory')}")
        
        # Vérifier la présence du RCP
        rcp = market_doc.get('rcp')
        if rcp:
            sections = rcp.get('sections', [])
            print(f"   - RCP sections: {len(sections)}")
            if sections:
                print(f"     Première section: {sections[0].get('title')}")
        
        # Vérifier medicine_ref
        medicine_ref = market_doc.get('medicine_ref')
        if medicine_ref:
            print(f"   - medicine_ref: {medicine_ref}")
            
            # Test 3: Vérifier la relation avec medicines_v3
            print("\n3. Test de la relation medicine_market -> medicines_v3...")
            medicine_doc = db.medicines_v3.find_one({"_id": medicine_ref})
            if medicine_doc:
                print(f"   ✓ Medicine trouvé: {medicine_doc['_id']}")
                print(f"   - inns: {medicine_doc.get('inns')}")
                print(f"   - countries: {medicine_doc.get('countries')}")
                print(f"   - substance_labels: {medicine_doc.get('substance_labels')}")
                
                # Test 4: Vérifier la relation avec substances_v3
                substance_ref_ids = medicine_doc.get('substance_ref_ids', [])
                if substance_ref_ids:
                    print(f"\n4. Test de la relation medicines_v3 -> substances_v3...")
                    print(f"   - {len(substance_ref_ids)} substance(s) référencée(s)")
                    
                    for sub_ref in substance_ref_ids[:3]:  # Limiter à 3
                        sub_doc = db.substances_v3.find_one({"_id": sub_ref})
                        if sub_doc:
                            print(f"   ✓ Substance: {sub_doc.get('label')}")
                            
                            # Vérifier les données PubChem
                            pubchem = sub_doc.get('sources', {}).get('pubchem')
                            if pubchem:
                                print(f"     - PubChem CID: {pubchem.get('cid')}")
                                summary = pubchem.get('summary', {})
                                if summary:
                                    print(f"     - Formule: {summary.get('molecular_formula')}")
            else:
                print(f"   ✗ Medicine non trouvé pour _id: {medicine_ref}")
        else:
            print("   ⚠ Pas de medicine_ref dans ce document")
    else:
        print("   ✗ Aucun document medicine_market trouvé")
    
    print("\n" + "=" * 80)
    print("FIN DES TESTS")
    print("=" * 80)


def test_url_patterns():
    """Test des différents patterns d'URL pour accéder aux médicaments"""
    print("\n" + "=" * 80)
    print("TEST DES PATTERNS D'URL")
    print("=" * 80)
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Récupérer un exemple de document
    market_doc = db.medicine_market.find_one()
    
    if market_doc:
        _id = market_doc['_id']
        cis = market_doc.get('cis')
        market_key = market_doc.get('market_key')
        
        print(f"\nDocument de test: {market_doc.get('brand_title')}")
        print(f"\nURLs possibles pour accéder à ce médicament:")
        print(f"1. Par _id:        /medicine-market/{_id}")
        if market_key:
            print(f"2. Par market_key: /medicine-market/{market_key}")
        if cis:
            print(f"3. Par CIS:        /medicine-market/{cis}")
        
        print(f"\nExemple de test avec curl:")
        print(f"curl http://localhost:5000/medicine-market/{_id}")


def show_rcp_structure():
    """Affiche la structure d'un RCP pour validation"""
    print("\n" + "=" * 80)
    print("STRUCTURE D'UN RCP")
    print("=" * 80)
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Trouver un document avec RCP
    market_doc = db.medicine_market.find_one({"rcp.sections": {"$exists": True}})
    
    if market_doc:
        rcp = market_doc.get('rcp', {})
        print(f"\nDocument: {market_doc.get('brand_title')}")
        print(f"\nMétadonnées RCP:")
        metadata = rcp.get('metadata', {})
        for key, value in metadata.items():
            if key != 'medicine_details':
                print(f"  {key}: {value}")
        
        print(f"\nSections RCP ({len(rcp.get('sections', []))}):")
        for i, section in enumerate(rcp.get('sections', [])[:3], 1):
            print(f"\n  Section {i}: {section.get('title')}")
            print(f"  - Content items: {len(section.get('content', []))}")
            print(f"  - Subsections: {len(section.get('subsections', []))}")
            
            # Afficher un exemple de contenu
            if section.get('content'):
                first_item = section['content'][0]
                if isinstance(first_item, dict):
                    text = first_item.get('text', '')[:100]
                    print(f"  - Premier contenu: {text}...")


if __name__ == "__main__":
    try:
        test_v3_structure()
        test_url_patterns()
        show_rcp_structure()
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
