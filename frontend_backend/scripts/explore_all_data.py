#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour explorer toutes les données disponibles dans medicine_market
"""
import sys
import os

if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

from pymongo import MongoClient
import json

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "medicsearch"

def explore_data_sources():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    
    # Récupérer un document complet
    market_doc = db.medicine_market.find_one({"cis": "61266250"})
    
    print("=" * 80)
    print("EXPLORATION DES DONNÉES DISPONIBLES")
    print("=" * 80)
    
    # 1. RCP
    print("\n📄 RCP (Résumé des Caractéristiques du Produit)")
    rcp = market_doc.get('rcp', {})
    if rcp:
        print(f"  ✓ Metadata: {len(rcp.get('metadata', {}))} champs")
        print(f"  ✓ Sections: {len(rcp.get('sections', []))} sections")
        metadata = rcp.get('metadata', {})
        print(f"    - Title: {metadata.get('title')}")
        print(f"    - Update date: {metadata.get('update_date')}")
        print(f"    - URL: {metadata.get('url')[:50]}...")
    
    # 2. Thériaque
    print("\n💊 THÉRIAQUE")
    theriaque = market_doc.get('theriaque', {})
    if theriaque:
        migrations = theriaque.get('migrations', {}).get('v2', [])
        if migrations:
            data = migrations[0]
            print(f"  ✓ Source: {data.get('meta', {}).get('source')}")
            print(f"  ✓ SP ID: {data.get('meta', {}).get('sp_id')}")
            
            # Interactions
            interactions = data.get('interactions', {})
            if interactions:
                print(f"  ✓ Interactions: {interactions.get('text', 'N/A')[:50]}...")
            
            # Contre-indications
            c_indic = data.get('c_indic', {})
            if c_indic:
                terrains = c_indic.get('terrains', [])
                print(f"  ✓ Contre-indications: {len(terrains)} terrains")
                for t in terrains[:3]:
                    print(f"    - {t.get('intitule')}: {t.get('niveau', [''])[0]}")
            
            # Indications
            indic = data.get('indic', {})
            if indic:
                print(f"  ✓ Indications: {indic.get('text', 'N/A')[:50]}...")
    
    # 3. Medicine V3 (via medicine_ref)
    print("\n🔗 MEDICINES_V3 (via medicine_ref)")
    medicine_ref = market_doc.get('medicine_ref')
    if medicine_ref:
        medicine_doc = db.medicines_v3.find_one({"_id": medicine_ref})
        if medicine_doc:
            print(f"  ✓ INNs: {medicine_doc.get('inns', [])}")
            print(f"  ✓ Countries: {medicine_doc.get('countries', [])}")
            print(f"  ✓ Substance labels: {len(medicine_doc.get('substance_labels', []))} labels")
            
            # 4. Substances V3 (via substance_ref_ids)
            substance_ref_ids = medicine_doc.get('substance_ref_ids', [])
            if substance_ref_ids:
                print(f"\n🧬 SUBSTANCES_V3 ({len(substance_ref_ids)} substances)")
                for i, sub_ref in enumerate(substance_ref_ids[:2], 1):
                    sub_doc = db.substances_v3.find_one({"_id": sub_ref})
                    if sub_doc:
                        print(f"\n  Substance {i}: {sub_doc.get('label')}")
                        
                        # PubChem
                        pubchem = sub_doc.get('sources', {}).get('pubchem', {})
                        if pubchem:
                            print(f"    📊 PubChem:")
                            print(f"      - CID: {pubchem.get('cid')}")
                            summary = pubchem.get('summary', {})
                            if summary:
                                print(f"      - Formule: {summary.get('molecular_formula')}")
                                print(f"      - Poids: {summary.get('molecular_weight')}")
                                print(f"      - SMILES: {summary.get('canonical_smiles', 'N/A')[:50]}...")
                            
                            synonyms = pubchem.get('synonyms_top', [])[:5]
                            if synonyms:
                                print(f"      - Synonymes: {', '.join(synonyms[:3])}")
                        
                        # DrugBank
                        drugbank = sub_doc.get('sources', {}).get('drugbank', {})
                        if drugbank:
                            print(f"    💊 DrugBank:")
                            print(f"      - ID: {drugbank.get('drugbank_id')}")
                            print(f"      - Label: {drugbank.get('label')}")
                            print(f"      - CAS: {drugbank.get('cas')}")
                            print(f"      - UNII: {drugbank.get('unii')}")
    
    print("\n" + "=" * 80)
    print("RÉSUMÉ DES SOURCES DISPONIBLES")
    print("=" * 80)
    print("✓ RCP (ANSM) - Sections complètes")
    print("✓ Thériaque - Interactions, contre-indications, indications")
    print("✓ PubChem - Propriétés chimiques, synonymes, structure")
    print("✓ DrugBank - Informations pharmacologiques")
    print("=" * 80)

if __name__ == "__main__":
    try:
        explore_data_sources()
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
