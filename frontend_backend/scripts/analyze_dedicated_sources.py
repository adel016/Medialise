#!/usr/bin/env python3
"""
Investigation finale - comprendre comment les sources sont liées
via les collections dédiées: pharmgkb_drugs, drugbank_raw_chunks, pubchem_compound_sections
"""

from pymongo import MongoClient
from bson import ObjectId

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    print("=" * 100)
    print("ANALYSE DES COLLECTIONS DÉDIÉES PAR SOURCE")
    print("=" * 100)
    
    # 1. PharmGKB
    print("\n💊 PHARMGKB_DRUGS:")
    print("-" * 100)
    
    abacavir_pharmgkb = db.pharmgkb_drugs.find_one({
        'name': {'$regex': 'abacavir', '$options': 'i'}
    })
    
    if abacavir_pharmgkb:
        print(f"  ✅ Abacavir trouvé dans pharmgkb_drugs!")
        print(f"  _id: {abacavir_pharmgkb.get('_id')}")
        print(f"  name: {abacavir_pharmgkb.get('name')}")
        print(f"  pharmgkb_id: {abacavir_pharmgkb.get('pharmgkb_id')}")
        print(f"\n  Tous les champs: {list(abacavir_pharmgkb.keys())}")
    
    # Statistiques
    sample_pharmgkb = db.pharmgkb_drugs.find_one()
    print(f"\n  Structure type:")
    if sample_pharmgkb:
        print(f"    Champs: {list(sample_pharmgkb.keys())}")
    
    # 2. DrugBank
    print("\n\n💊 DRUGBANK_RAW_CHUNKS:")
    print("-" * 100)
    
    abacavir_drugbank = db.drugbank_raw_chunks.find_one({
        '$or': [
            {'data.name': {'$regex': 'abacavir', '$options': 'i'}},
            {'drugbank_id': {'$regex': 'abacavir', '$options': 'i'}}
        ]
    })
    
    if abacavir_drugbank:
        print(f"  ✅ Abacavir trouvé dans drugbank_raw_chunks!")
        print(f"  _id: {abacavir_drugbank.get('_id')}")
        print(f"  drugbank_id: {abacavir_drugbank.get('drugbank_id')}")
        print(f"  kind: {abacavir_drugbank.get('kind')}")
        data = abacavir_drugbank.get('data')
        if isinstance(data, dict):
            print(f"  data keys: {list(data.keys())[:10]}")
        elif isinstance(data, list):
            print(f"  data: liste de {len(data)} éléments")
        else:
            print(f"  data type: {type(data)}")
    
    sample_drugbank = db.drugbank_raw_chunks.find_one()
    print(f"\n  Structure type:")
    if sample_drugbank:
        print(f"    Champs: {list(sample_drugbank.keys())}")
        print(f"    drugbank_id: {sample_drugbank.get('drugbank_id')}")
        print(f"    kind: {sample_drugbank.get('kind')}")
    
    # 3. PubChem
    print("\n\n💊 PUBCHEM_COMPOUND_SECTIONS:")
    print("-" * 100)
    
    sample_pubchem = db.pubchem_compound_sections.find_one()
    print(f"  Structure type:")
    if sample_pubchem:
        print(f"    Champs: {list(sample_pubchem.keys())}")
        if 'cid' in sample_pubchem:
            print(f"    cid (exemple): {sample_pubchem.get('cid')}")
        if 'heading' in sample_pubchem:
            print(f"    heading (exemple): {sample_pubchem.get('heading')}")
    
    # 4. Regarder medicine_market pour Theriaque
    print("\n\n💊 THERIAQUE (dans medicine_market):")
    print("-" * 100)
    
    theriaque_sample = db.medicine_market.find_one({
        'theriaque': {'$exists': True, '$ne': None}
    })
    
    if theriaque_sample:
        print(f"  ✅ Exemple avec Theriaque:")
        print(f"  _id: {theriaque_sample.get('_id')}")
        print(f"  brand_title: {theriaque_sample.get('brand_title')}")
        print(f"  theriaque type: {type(theriaque_sample.get('theriaque'))}")
        if isinstance(theriaque_sample.get('theriaque'), dict):
            print(f"  theriaque keys: {list(theriaque_sample.get('theriaque', {}).keys())}")
    
    # 5. RCP dans medicine_market
    print("\n\n📄 RCP (dans medicine_market):")
    print("-" * 100)
    
    rcp_sample = db.medicine_market.find_one({
        'rcp': {'$exists': True, '$ne': None}
    })
    
    if rcp_sample:
        print(f"  ✅ Exemple avec RCP:")
        print(f"  _id: {rcp_sample.get('_id')}")
        print(f"  brand_title: {rcp_sample.get('brand_title')}")
        print(f"  market_key: {rcp_sample.get('market_key')}")
        print(f"  rcp type: {type(rcp_sample.get('rcp'))}")
        if isinstance(rcp_sample.get('rcp'), dict):
            print(f"  rcp keys: {list(rcp_sample.get('rcp', {}).keys())}")
    
    # 6. Chercher les liens entre collections
    print("\n\n🔗 STRATÉGIE DE LIAISON:")
    print("=" * 100)
    
    print("""
    SOURCES DE DONNÉES IDENTIFIÉES:
    
    1. ANSM/BDPM (Base de données publique des médicaments)
       - Localisation: medicine_market.market_key (contient "BDPM")
       - Nombre: 7,749 médocs
       - Enrichissement: RCP (Résumé des Caractéristiques du Produit)
    
    2. Theriaque
       - Localisation: medicine_market.theriaque (objet avec données)
       - Nombre: 1,428 médocs
       - Type: Enrichissement direct dans medicine_market
    
    3. PharmGKB (Pharmacogénomique)
       - Localisation: pharmgkb_drugs (collection séparée)
       - Nombre: 3,703 drugs
       - Liaison: Par nom de substance (inns, medicine_key)
    
    4. DrugBank
       - Localisation: drugbank_raw_chunks (collection séparée)
       - Nombre: 19,025 chunks
       - Liaison: Par drugbank_id ou nom
    
    5. PubChem
       - Localisation: pubchem_compound_sections (collection séparée)
       - Nombre: 115,205 sections
       - Liaison: Par CID (Compound ID) ou nom de substance
    
    6. OpenFDA
       - Localisation: À vérifier - peut-être dans une autre collection ou enrichissement
    
    RECOMMANDATION POUR LES FILTRES:
    ================================
    
    Option A: FILTRES SIMPLES (pour la démo demain)
    ------------------------------------------------
    1. ANSM/BDPM: market_key LIKE '%BDPM%'
    2. Theriaque: medicine_market.theriaque EXISTS
    3. PharmGKB: JOIN avec pharmgkb_drugs par nom/substance
    4. DrugBank: JOIN avec drugbank_raw_chunks par nom
    5. PubChem: JOIN avec pubchem_compound_sections par substance
    
    Option B: PRE-CALCULER UN CHAMP 'sources' (meilleur)
    -----------------------------------------------------
    Ajouter un champ 'available_sources' dans medicine_market avec:
    ['BDPM', 'Theriaque', 'PharmGKB', 'DrugBank', 'PubChem', 'OpenFDA']
    
    Puis filtrer simplement avec:
    {available_sources: {$in: ['PharmGKB', 'DrugBank']}}
    """)
    
    # 7. Compter les médocs par source (estimation)
    print("\n\n📊 ESTIMATION DES MÉDOCS PAR SOURCE:")
    print("-" * 100)
    
    # BDPM
    bdpm_count = db.medicine_market.count_documents({'market_key': {'$regex': 'BDPM'}})
    print(f"  ANSM/BDPM: {bdpm_count:,} médocs")
    
    # Theriaque
    theriaque_count = db.medicine_market.count_documents({'theriaque': {'$exists': True, '$ne': None}})
    print(f"  Theriaque:  {theriaque_count:,} médocs")
    
    # RCP
    rcp_count = db.medicine_market.count_documents({'rcp': {'$exists': True, '$ne': None}})
    print(f"  RCP (ANSM): {rcp_count:,} médocs")
    
    # PharmGKB (estimation via substances)
    pharmgkb_drugs_count = db.pharmgkb_drugs.count_documents({})
    print(f"  PharmGKB:   {pharmgkb_drugs_count:,} drugs (collection dédiée)")
    
    # DrugBank
    drugbank_count = len(set([doc['drugbank_id'] for doc in db.drugbank_raw_chunks.find({}, {'drugbank_id': 1})]))
    print(f"  DrugBank:   ~{drugbank_count:,} drugs (collection dédiée)")
    
    # PubChem
    pubchem_compounds = db.pubchem_compound_sections.distinct('cid')
    print(f"  PubChem:    {len(pubchem_compounds):,} compounds (collection dédiée)")

if __name__ == '__main__':
    main()
