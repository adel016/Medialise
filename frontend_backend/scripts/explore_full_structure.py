#!/usr/bin/env python3
"""
Exploration complète de la structure de données pour comprendre 
l'enrichissement multi-sources avant d'implémenter les filtres
"""

from pymongo import MongoClient
from pprint import pprint
import json

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    print("=" * 100)
    print("EXPLORATION DE LA STRUCTURE MULTI-SOURCES")
    print("=" * 100)
    
    # 1. COLLECTIONS DISPONIBLES
    print("\n📚 COLLECTIONS DISPONIBLES:")
    print("-" * 100)
    collections = db.list_collection_names()
    for coll in sorted(collections):
        count = db[coll].count_documents({})
        print(f"  - {coll:30} : {count:,} documents")
    
    # 2. ABACAVIR - Exemple complet avec toutes les sources
    print("\n\n🔍 ANALYSE D'ABACAVIR (médoc le plus complet):")
    print("-" * 100)
    
    # Chercher abacavir dans medicine_market
    abacavir_markets = list(db.medicine_market.find(
        {'$or': [
            {'brand_title': {'$regex': 'abacavir', '$options': 'i'}},
            {'medicine_id': {'$regex': 'abacavir', '$options': 'i'}}
        ]}
    ).limit(3))
    
    print(f"\n  Trouvé {len(abacavir_markets)} entrées dans medicine_market")
    
    if abacavir_markets:
        for i, doc in enumerate(abacavir_markets, 1):
            print(f"\n  📦 Medicine Market #{i}:")
            print(f"     _id: {doc.get('_id')}")
            print(f"     market_key: {doc.get('market_key')}")
            print(f"     brand_title: {doc.get('brand_title')}")
            print(f"     medicine_ref: {doc.get('medicine_ref')}")
            print(f"     country: {doc.get('country')}")
            
            # Champs disponibles pour identifier les sources
            print(f"\n     Champs liés aux sources:")
            if doc.get('rcp'):
                print(f"       - rcp: {type(doc.get('rcp'))} avec {len(doc.get('rcp', {}))} clés")
            if doc.get('theriaque'):
                print(f"       - theriaque: {type(doc.get('theriaque'))}")
            if doc.get('source_urls'):
                print(f"       - source_urls: {doc.get('source_urls')}")
            
            # Explorer le medicine_ref lié
            if doc.get('medicine_ref'):
                med_doc = db.medicines_v3.find_one({'_id': doc['medicine_ref']})
                if med_doc:
                    print(f"\n  📋 Medicines_v3 lié (medicine_key: {med_doc.get('medicine_key')}):")
                    print(f"     _id: {med_doc.get('_id')}")
                    print(f"     inns: {med_doc.get('inns')}")
                    print(f"     countries: {med_doc.get('countries')}")
                    
                    # SOURCES ENRICHIES
                    print(f"\n     🌟 SOURCES D'ENRICHISSEMENT:")
                    sources_found = []
                    
                    if med_doc.get('drugbank'):
                        sources_found.append('DrugBank')
                        print(f"       ✅ DrugBank: {type(med_doc.get('drugbank'))}")
                        if isinstance(med_doc.get('drugbank'), dict):
                            print(f"          Clés: {list(med_doc.get('drugbank', {}).keys())[:10]}")
                    
                    if med_doc.get('openfda'):
                        sources_found.append('OpenFDA')
                        print(f"       ✅ OpenFDA: {type(med_doc.get('openfda'))}")
                    
                    if med_doc.get('pharmgkb'):
                        sources_found.append('PharmGKB')
                        print(f"       ✅ PharmGKB: {type(med_doc.get('pharmgkb'))}")
                    
                    if med_doc.get('pubchem'):
                        sources_found.append('PubChem')
                        print(f"       ✅ PubChem: {type(med_doc.get('pubchem'))}")
                    
                    if med_doc.get('theriaque'):
                        sources_found.append('Theriaque')
                        print(f"       ✅ Theriaque: {type(med_doc.get('theriaque'))}")
                    
                    # BDPM/ANSM via market_key
                    if doc.get('market_key') and 'BDPM' in doc.get('market_key', ''):
                        sources_found.append('ANSM/BDPM')
                        print(f"       ✅ ANSM/BDPM: via market_key")
                    
                    print(f"\n     📊 TOTAL SOURCES: {len(sources_found)} -> {', '.join(sources_found)}")
                    
                    print(f"\n     Tous les champs disponibles ({len(med_doc.keys())} champs):")
                    print(f"     {list(med_doc.keys())}")
    
    # 3. STATISTIQUES PAR SOURCE
    print("\n\n📊 STATISTIQUES D'ENRICHISSEMENT PAR SOURCE:")
    print("-" * 100)
    
    # Compter dans medicines_v3
    stats = {
        'DrugBank': db.medicines_v3.count_documents({'drugbank': {'$exists': True, '$ne': None}}),
        'OpenFDA': db.medicines_v3.count_documents({'openfda': {'$exists': True, '$ne': None}}),
        'PharmGKB': db.medicines_v3.count_documents({'pharmgkb': {'$exists': True, '$ne': None}}),
        'PubChem': db.medicines_v3.count_documents({'pubchem': {'$exists': True, '$ne': None}}),
        'Theriaque': db.medicines_v3.count_documents({'theriaque': {'$exists': True, '$ne': None}}),
    }
    
    # BDPM dans medicine_market
    bdpm_count = db.medicine_market.count_documents({'market_key': {'$regex': 'BDPM'}})
    stats['ANSM/BDPM'] = bdpm_count
    
    print("\n  Dans medicines_v3 (enrichissements):")
    for source, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        if source != 'ANSM/BDPM':
            print(f"    - {source:20} : {count:,} médocs")
    
    print(f"\n  Dans medicine_market:")
    print(f"    - ANSM/BDPM (market_key) : {bdpm_count:,} médocs")
    
    # 4. STRUCTURE DES SUBSTANCES
    print("\n\n🧪 STRUCTURE SUBSTANCES_V3:")
    print("-" * 100)
    
    abacavir_sub = db.substances_v3.find_one({'label': {'$regex': 'abacavir', '$options': 'i'}})
    if abacavir_sub:
        print(f"  Exemple: {abacavir_sub.get('label')}")
        print(f"  _id: {abacavir_sub.get('_id')}")
        print(f"  Champs disponibles: {list(abacavir_sub.keys())}")
    
    # 5. DRUGBANK_RAW_CHUNKS
    print("\n\n💊 DRUGBANK_RAW_CHUNKS (non exploité):")
    print("-" * 100)
    
    if 'drugbank_raw_chunks' in collections:
        chunk_count = db.drugbank_raw_chunks.count_documents({})
        print(f"  Total documents: {chunk_count:,}")
        
        sample_chunk = db.drugbank_raw_chunks.find_one()
        if sample_chunk:
            print(f"  Exemple de structure:")
            print(f"    Clés: {list(sample_chunk.keys())}")
            if 'drug_id' in sample_chunk:
                print(f"    drug_id: {sample_chunk.get('drug_id')}")
            if 'name' in sample_chunk:
                print(f"    name: {sample_chunk.get('name')}")
    
    # 6. PROPOSITION DE STRATÉGIE DE FILTRAGE
    print("\n\n💡 RECOMMANDATIONS POUR LE SYSTÈME DE FILTRES:")
    print("=" * 100)
    
    print("""
    Basé sur l'analyse, voici la structure détectée:
    
    1. MEDICINES_V3 contient les enrichissements multi-sources:
       - Champs: drugbank, openfda, pharmgkb, pubchem, theriaque
       - Un médoc peut avoir 1, 2, 3... jusqu'à 6 sources
    
    2. MEDICINE_MARKET est la couche d'affichage:
       - Contient market_key avec BDPM pour identifier l'ANSM
       - Référence medicines_v3 via medicine_ref
    
    3. STRATÉGIE DE FILTRAGE RECOMMANDÉE:
       ✅ Ajouter un filtre "Source de données" avec cases à cocher multiples
       ✅ Permettre de sélectionner plusieurs sources simultanément
       ✅ Filtrer via medicines_v3 pour DrugBank, OpenFDA, PharmGKB, PubChem, Theriaque
       ✅ Filtrer via market_key pour ANSM/BDPM
       ✅ Afficher le nombre de médocs disponibles par source
    
    4. POUR LA DÉMO:
       ✅ Rechercher "abacavir" -> montrer toutes les sources
       ✅ Filtrer par "PharmGKB" -> montrer les médocs avec données pharmacogénomiques
       ✅ Filtrer par "DrugBank" -> montrer l'enrichissement DrugBank
    """)
    
    # 7. EXEMPLES DE MÉDOCS PAR SOURCE
    print("\n\n🎯 EXEMPLES DE MÉDOCS PAR SOURCE (pour tests):")
    print("-" * 100)
    
    # PharmGKB
    pharmgkb_example = db.medicines_v3.find_one(
        {'pharmgkb': {'$exists': True, '$ne': None}},
        {'medicine_key': 1, 'inns': 1}
    )
    if pharmgkb_example:
        print(f"  PharmGKB: {pharmgkb_example.get('medicine_key')} / {pharmgkb_example.get('inns')}")
    
    # DrugBank
    drugbank_example = db.medicines_v3.find_one(
        {'drugbank': {'$exists': True, '$ne': None}},
        {'medicine_key': 1, 'inns': 1}
    )
    if drugbank_example:
        print(f"  DrugBank: {drugbank_example.get('medicine_key')} / {drugbank_example.get('inns')}")
    
    # OpenFDA
    openfda_example = db.medicines_v3.find_one(
        {'openfda': {'$exists': True, '$ne': None}},
        {'medicine_key': 1, 'inns': 1}
    )
    if openfda_example:
        print(f"  OpenFDA: {openfda_example.get('medicine_key')} / {openfda_example.get('inns')}")

if __name__ == '__main__':
    main()
