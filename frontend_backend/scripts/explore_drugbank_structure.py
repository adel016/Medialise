#!/usr/bin/env python3
"""
Explorer la structure DrugBank pour comprendre comment identifier 
les médocs qui sont dans DrugBank et les lier à medicine_market
"""

from pymongo import MongoClient

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    print("=" * 100)
    print("EXPLORATION DRUGBANK POUR FILTRAGE")
    print("=" * 100)
    
    # 1. Structure de drugbank_raw_chunks
    print("\n📦 STRUCTURE drugbank_raw_chunks:")
    print("-" * 100)
    
    sample = db.drugbank_raw_chunks.find_one()
    if sample:
        print(f"  Champs: {list(sample.keys())}")
        print(f"  drugbank_id: {sample.get('drugbank_id')}")
        print(f"  kind: {sample.get('kind')}")
        
        # Voir les différents 'kind' disponibles
        kinds = db.drugbank_raw_chunks.distinct('kind')
        print(f"\n  Types de chunks disponibles:")
        for kind in kinds:
            count = db.drugbank_raw_chunks.count_documents({'kind': kind})
            print(f"    - {kind}: {count} chunks")
    
    # 2. Chercher les chunks de type 'general' ou 'basic' qui contiennent le nom
    print("\n\n🔍 CHUNKS AVEC INFORMATIONS DE BASE:")
    print("-" * 100)
    
    # Chercher un exemple avec le nom
    general_chunk = db.drugbank_raw_chunks.find_one({'kind': 'general'})
    if general_chunk:
        print(f"\n  Exemple chunk 'general':")
        print(f"    drugbank_id: {general_chunk.get('drugbank_id')}")
        data = general_chunk.get('data', {})
        if isinstance(data, dict):
            print(f"    data keys: {list(data.keys())[:15]}")
            if 'name' in data:
                print(f"    name: {data.get('name')}")
        elif isinstance(data, list) and len(data) > 0:
            print(f"    data: liste de {len(data)} éléments")
            if isinstance(data[0], dict):
                print(f"    Premier élément keys: {list(data[0].keys())[:10]}")
    
    # 3. Vérifier s'il existe une collection medicines avec source DrugBank
    print("\n\n📚 COLLECTION 'medicines' - Source DrugBank:")
    print("-" * 100)
    
    # Chercher dans medicines
    drugbank_in_medicines = db.medicines.find_one({'source': {'$regex': 'drugbank', '$options': 'i'}})
    if drugbank_in_medicines:
        print(f"  ✅ Trouvé médoc avec source DrugBank dans 'medicines':")
        print(f"    _id: {drugbank_in_medicines.get('_id')}")
        print(f"    title: {drugbank_in_medicines.get('title')}")
        print(f"    source: {drugbank_in_medicines.get('source')}")
    else:
        print(f"  ❌ Aucun médoc avec source='drugbank' dans 'medicines'")
    
    # 4. Vérifier les liens medicine_market -> DrugBank
    print("\n\n🔗 LIENS medicine_market -> DrugBank:")
    print("-" * 100)
    
    # Chercher si medicine_id correspond à drugbank_id
    drugbank_ids = set(db.drugbank_raw_chunks.distinct('drugbank_id'))
    print(f"  Total DrugBank IDs: {len(drugbank_ids)}")
    
    # Chercher dans medicine_market
    market_with_db_id = db.medicine_market.find_one({
        'medicine_id': {'$in': list(drugbank_ids)[:100]}  # Test avec les 100 premiers
    })
    
    if market_with_db_id:
        print(f"\n  ✅ Trouvé medicine_market avec medicine_id = drugbank_id:")
        print(f"    _id: {market_with_db_id.get('_id')}")
        print(f"    medicine_id: {market_with_db_id.get('medicine_id')}")
        print(f"    brand_title: {market_with_db_id.get('brand_title')}")
    else:
        print(f"\n  ❌ Aucun medicine_market avec medicine_id dans drugbank_ids")
    
    # 5. Stratégie alternative: Chercher par nom
    print("\n\n💡 STRATÉGIE DE LIAISON:")
    print("-" * 100)
    
    # Prendre un DrugBank ID et chercher son nom
    db_id = list(drugbank_ids)[0]
    chunks_for_drug = list(db.drugbank_raw_chunks.find({'drugbank_id': db_id}))
    
    print(f"\n  DrugBank ID exemple: {db_id}")
    print(f"  Chunks pour ce drug: {len(chunks_for_drug)}")
    
    # Chercher le nom dans les chunks
    drug_name = None
    for chunk in chunks_for_drug:
        data = chunk.get('data', {})
        if isinstance(data, dict) and 'name' in data:
            drug_name = data['name']
            break
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and 'name' in item:
                    drug_name = item['name']
                    break
    
    if drug_name:
        print(f"  Nom trouvé: {drug_name}")
        
        # Chercher ce nom dans medicine_market
        market_by_name = db.medicine_market.find_one({
            'brand_title': {'$regex': drug_name, '$options': 'i'}
        })
        
        if market_by_name:
            print(f"\n  ✅ Trouvé dans medicine_market par nom:")
            print(f"    _id: {market_by_name.get('_id')}")
            print(f"    brand_title: {market_by_name.get('brand_title')}")
            print(f"    data_sources: {market_by_name.get('data_sources', [])}")
        else:
            print(f"\n  ❌ Pas trouvé dans medicine_market par nom")
    
    # 6. Vérifier si des médocs ont déjà DrugBank dans data_sources
    print("\n\n📊 MÉDOCS AVEC DrugBank DANS data_sources:")
    print("-" * 100)
    
    drugbank_count = db.medicine_market.count_documents({'data_sources': 'DrugBank'})
    print(f"  Total: {drugbank_count} médocs")
    
    if drugbank_count > 0:
        sample_db = db.medicine_market.find_one({'data_sources': 'DrugBank'})
        print(f"\n  Exemple:")
        print(f"    _id: {sample_db.get('_id')}")
        print(f"    brand_title: {sample_db.get('brand_title')}")
        print(f"    medicine_id: {sample_db.get('medicine_id')}")
        print(f"    data_sources: {sample_db.get('data_sources')}")
    
    # 7. RECOMMANDATION
    print("\n\n" + "=" * 100)
    print("💡 RECOMMANDATIONS:")
    print("=" * 100)
    print("""
    Pour intégrer DrugBank comme source:
    
    Option 1: Enrichissement (ce qui a été fait)
    - DrugBank enrichit les médocs existants dans medicine_market
    - Pas une source primaire mais des données supplémentaires
    - Nécessite de créer un champ 'drugbank_enrichment' dans medicine_market
    
    Option 2: Source primaire (si vous voulez médocs DrugBank seuls)
    - Créer des entrées medicine_market pour chaque DrugBank ID
    - Lier via medicine_id = drugbank_id
    - Ajouter 'DrugBank' dans data_sources
    
    Option 3: Collection séparée (recommandé pour la démo)
    - Garder drugbank_raw_chunks séparé
    - Créer un endpoint /drugbank-search pour chercher dans DrugBank
    - Montrer les données DrugBank dans une section dédiée
    """)

if __name__ == '__main__':
    main()
