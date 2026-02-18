#!/usr/bin/env python3
"""
Investigation approfondie - chercher où sont les enrichissements
DrugBank, PharmGKB, OpenFDA, PubChem, Theriaque
"""

from pymongo import MongoClient
from pprint import pprint

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    print("=" * 100)
    print("RECHERCHE DES ENRICHISSEMENTS MULTI-SOURCES")
    print("=" * 100)
    
    # 1. Chercher dans l'ancienne collection 'medicines'
    print("\n📦 COLLECTION 'medicines' (1,601 documents - ancienne structure):")
    print("-" * 100)
    
    # Chercher abacavir
    abacavir_old = db.medicines.find_one({
        '$or': [
            {'title': {'$regex': 'abacavir', '$options': 'i'}},
            {'drug_name': {'$regex': 'abacavir', '$options': 'i'}},
            {'inns': {'$regex': 'abacavir', '$options': 'i'}}
        ]
    })
    
    if abacavir_old:
        print(f"\n  ✅ Abacavir trouvé dans 'medicines'!")
        print(f"  _id: {abacavir_old.get('_id')}")
        print(f"  title: {abacavir_old.get('title')}")
        print(f"\n  Tous les champs ({len(abacavir_old.keys())} champs):")
        for key in sorted(abacavir_old.keys()):
            value = abacavir_old.get(key)
            if isinstance(value, (dict, list)):
                print(f"    - {key:30} : {type(value).__name__} ({len(value)} items)")
            else:
                print(f"    - {key:30} : {type(value).__name__}")
        
        # Vérifier les sources
        print(f"\n  🌟 SOURCES D'ENRICHISSEMENT:")
        sources = []
        
        if abacavir_old.get('drugbank'):
            sources.append('DrugBank')
            print(f"    ✅ DrugBank")
            if isinstance(abacavir_old['drugbank'], dict):
                print(f"       Clés DrugBank: {list(abacavir_old['drugbank'].keys())[:15]}")
        
        if abacavir_old.get('openfda'):
            sources.append('OpenFDA')
            print(f"    ✅ OpenFDA")
        
        if abacavir_old.get('pharmgkb'):
            sources.append('PharmGKB')
            print(f"    ✅ PharmGKB")
        
        if abacavir_old.get('pubchem'):
            sources.append('PubChem')
            print(f"    ✅ PubChem")
        
        if abacavir_old.get('theriaque'):
            sources.append('Theriaque')
            print(f"    ✅ Theriaque")
        
        if abacavir_old.get('ansm') or abacavir_old.get('bdpm'):
            sources.append('ANSM/BDPM')
            print(f"    ✅ ANSM/BDPM")
        
        print(f"\n  📊 TOTAL SOURCES POUR ABACAVIR: {len(sources)} -> {', '.join(sources)}")
    
    # 2. Statistiques des enrichissements dans 'medicines'
    print("\n\n📊 STATISTIQUES DES ENRICHISSEMENTS DANS 'medicines':")
    print("-" * 100)
    
    stats_medicines = {
        'DrugBank': db.medicines.count_documents({'drugbank': {'$exists': True, '$ne': None}}),
        'OpenFDA': db.medicines.count_documents({'openfda': {'$exists': True, '$ne': None}}),
        'PharmGKB': db.medicines.count_documents({'pharmgkb': {'$exists': True, '$ne': None}}),
        'PubChem': db.medicines.count_documents({'pubchem': {'$exists': True, '$ne': None}}),
        'Theriaque': db.medicines.count_documents({'theriaque': {'$exists': True, '$ne': None}}),
        'ANSM': db.medicines.count_documents({'ansm': {'$exists': True, '$ne': None}}),
        'RCP': db.medicines.count_documents({'rcp': {'$exists': True, '$ne': None}}),
    }
    
    for source, count in sorted(stats_medicines.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  - {source:20} : {count:,} médocs enrichis")
    
    # 3. Vérifier medicine_market pour les enrichissements Theriaque
    print("\n\n📦 ENRICHISSEMENTS DANS 'medicine_market':")
    print("-" * 100)
    
    stats_market = {
        'Theriaque': db.medicine_market.count_documents({'theriaque': {'$exists': True, '$ne': None}}),
        'RCP': db.medicine_market.count_documents({'rcp': {'$exists': True, '$ne': None}}),
    }
    
    for source, count in sorted(stats_market.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  - {source:20} : {count:,} médocs enrichis")
    
    # 4. Vérifier les collections dédiées
    print("\n\n📚 COLLECTIONS DÉDIÉES PAR SOURCE:")
    print("-" * 100)
    
    print(f"  - pharmgkb_drugs          : {db.pharmgkb_drugs.count_documents({}):,} documents")
    print(f"  - pharmgkb_relationships  : {db.pharmgkb_relationships.count_documents({}):,} documents")
    print(f"  - drugbank_raw_chunks     : {db.drugbank_raw_chunks.count_documents({}):,} documents")
    print(f"  - pubchem_compound_sections: {db.pubchem_compound_sections.count_documents({}):,} documents")
    
    # 5. Exemples de documents par source
    print("\n\n🎯 EXEMPLES DE MÉDOCS ENRICHIS (pour filtres):")
    print("-" * 100)
    
    # PharmGKB
    pharmgkb_ex = db.medicines.find_one(
        {'pharmgkb': {'$exists': True, '$ne': None}},
        {'title': 1, '_id': 1}
    )
    if pharmgkb_ex:
        print(f"\n  PharmGKB:")
        print(f"    _id: {pharmgkb_ex['_id']}")
        print(f"    title: {pharmgkb_ex.get('title')}")
    
    # DrugBank
    drugbank_ex = db.medicines.find_one(
        {'drugbank': {'$exists': True, '$ne': None}},
        {'title': 1, '_id': 1}
    )
    if drugbank_ex:
        print(f"\n  DrugBank:")
        print(f"    _id: {drugbank_ex['_id']}")
        print(f"    title: {drugbank_ex.get('title')}")
    
    # OpenFDA
    openfda_ex = db.medicines.find_one(
        {'openfda': {'$exists': True, '$ne': None}},
        {'title': 1, '_id': 1}
    )
    if openfda_ex:
        print(f"\n  OpenFDA:")
        print(f"    _id: {openfda_ex['_id']}")
        print(f"    title: {openfda_ex.get('title')}")
    
    # PubChem
    pubchem_ex = db.medicines.find_one(
        {'pubchem': {'$exists': True, '$ne': None}},
        {'title': 1, '_id': 1}
    )
    if pubchem_ex:
        print(f"\n  PubChem:")
        print(f"    _id: {pubchem_ex['_id']}")
        print(f"    title: {pubchem_ex.get('title')}")
    
    # Theriaque
    theriaque_ex = db.medicines.find_one(
        {'theriaque': {'$exists': True, '$ne': None}},
        {'title': 1, '_id': 1}
    )
    if theriaque_ex:
        print(f"\n  Theriaque:")
        print(f"    _id: {theriaque_ex['_id']}")
        print(f"    title: {theriaque_ex.get('title')}")
    
    # 6. Comprendre la relation medicines -> medicine_market
    print("\n\n🔗 RELATION 'medicines' ↔ 'medicine_market':")
    print("-" * 100)
    
    if abacavir_old:
        # Chercher les medicine_market liés
        abacavir_id = abacavir_old['_id']
        
        # Chercher par medicine_id
        markets = list(db.medicine_market.find({
            '$or': [
                {'medicine_id': str(abacavir_id)},
                {'medicine_id': abacavir_id}
            ]
        }).limit(5))
        
        print(f"\n  Abacavir (_id: {abacavir_id})")
        print(f"  Entrées medicine_market trouvées: {len(markets)}")
        
        if markets:
            for i, market in enumerate(markets, 1):
                print(f"\n    Market #{i}:")
                print(f"      _id: {market.get('_id')}")
                print(f"      brand_title: {market.get('brand_title')}")
                print(f"      medicine_id: {market.get('medicine_id')}")
                print(f"      medicine_ref: {market.get('medicine_ref')}")
    
    print("\n\n" + "=" * 100)
    print("💡 CONCLUSIONS:")
    print("=" * 100)
    print("""
    Les enrichissements sont dans la collection 'medicines' (1,601 documents) !
    
    STRATÉGIE DE FILTRAGE:
    1. Filtrer d'abord dans 'medicines' par source (drugbank, pharmgkb, etc.)
    2. Récupérer les _id des medicines filtrées
    3. Trouver les medicine_market liés via medicine_id ou medicine_ref
    4. Ajouter aussi le filtre BDPM via market_key dans medicine_market
    """)

if __name__ == '__main__':
    main()
