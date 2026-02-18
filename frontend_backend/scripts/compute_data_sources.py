#!/usr/bin/env python3
"""
Script pour calculer et ajouter le champ 'data_sources' dans medicine_market.
Ce champ contiendra un array des sources de données disponibles pour chaque médoc.

Sources possibles: ANSM, Theriaque, PharmGKB, DrugBank, PubChem, OpenFDA
"""

from pymongo import MongoClient, UpdateOne
from tqdm import tqdm
import time

def main():
    print("=" * 100)
    print("CALCUL DES SOURCES DE DONNÉES POUR MEDICINE_MARKET")
    print("=" * 100)
    
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    # Étape 1: Charger les données de référence des collections dédiées
    print("\n📚 Chargement des collections de référence...")
    
    # PharmGKB: Créer un set des noms normalisés
    print("  - Chargement PharmGKB...")
    pharmgkb_names = set()
    pharmgkb_synonyms = {}
    for doc in db.pharmgkb_drugs.find({}, {'name': 1, 'synonyms': 1}):
        name = doc.get('name', '').strip().upper()
        if name:
            pharmgkb_names.add(name)
        
        syns = doc.get('synonyms', [])
        if isinstance(syns, list):
            for syn in syns:
                if isinstance(syn, str) and syn.strip():
                    syn_norm = syn.strip().upper()
                    pharmgkb_names.add(syn_norm)
    
    print(f"     ✅ {len(pharmgkb_names):,} noms PharmGKB chargés")
    
    # DrugBank: Pas besoin de charger drugbank_raw_chunks, 
    # on va chercher dans substances_v3.sources.drugbank.drugbank_id
    
    # PubChem: Pas besoin de charger, 
    # on va chercher dans substances_v3.sources.pubchem.cid
    
    # Étape 2: Créer un index des substances
    print("\n🧪 Indexation des substances...")
    substance_to_pharmgkb = {}
    substance_to_drugbank = {}
    substance_to_pubchem = {}
    
    # Parcourir toutes les substances et extraire les sources
    for sub in tqdm(db.substances_v3.find({}, {'_id': 1, 'label': 1, 'label_normalized': 1, 'sources': 1}), 
                    desc="Substances → Sources"):
        sub_id = sub['_id']
        label = (sub.get('label') or '').strip().upper()
        label_norm = (sub.get('label_normalized') or '').strip().upper()
        sources = sub.get('sources', {})
        
        # PharmGKB: via nom
        if label in pharmgkb_names or label_norm in pharmgkb_names:
            substance_to_pharmgkb[sub_id] = True
        
        # DrugBank: via sources.drugbank.drugbank_id
        if isinstance(sources, dict) and sources.get('drugbank', {}).get('drugbank_id'):
            substance_to_drugbank[sub_id] = True
        
        # PubChem: via sources.pubchem.cid
        if isinstance(sources, dict) and sources.get('pubchem', {}).get('cid'):
            substance_to_pubchem[sub_id] = True
    
    print(f"  ✅ {len(substance_to_pharmgkb):,} substances liées à PharmGKB")
    print(f"  ✅ {len(substance_to_drugbank):,} substances liées à DrugBank")
    print(f"  ✅ {len(substance_to_pubchem):,} substances liées à PubChem")
    
    # Étape 3: Traiter tous les medicine_market
    print("\n💊 Calcul des sources pour medicine_market...")
    
    total = db.medicine_market.count_documents({})
    batch_size = 1000
    updated_count = 0
    stats = {
        'ANSM': 0,
        'Theriaque': 0,
        'PharmGKB': 0,
        'DrugBank': 0,
        'PubChem': 0,
        'OpenFDA': 0
    }
    
    with tqdm(total=total, desc="Processing") as pbar:
        skip = 0
        while skip < total:
            markets = list(db.medicine_market.find({}).skip(skip).limit(batch_size))
            
            bulk_operations = []
            
            for market in markets:
                sources = []
                
                # 1. ANSM/BDPM
                market_key = market.get('market_key', '')
                if 'BDPM' in market_key or market.get('rcp'):
                    sources.append('ANSM')
                    stats['ANSM'] += 1
                
                # 2. Theriaque
                if market.get('theriaque'):
                    sources.append('Theriaque')
                    stats['Theriaque'] += 1
                
                # 3. PharmGKB - via les substances du medicine_ref
                medicine_ref = market.get('medicine_ref')
                if medicine_ref:
                    med = db.medicines_v3.find_one(
                        {'_id': medicine_ref},
                        {'substance_ref_ids': 1}
                    )
                    
                    if med and med.get('substance_ref_ids'):
                        # PharmGKB
                        for sub_id in med['substance_ref_ids']:
                            if sub_id in substance_to_pharmgkb:
                                sources.append('PharmGKB')
                                stats['PharmGKB'] += 1
                                break
                        
                        # DrugBank
                        for sub_id in med['substance_ref_ids']:
                            if sub_id in substance_to_drugbank:
                                sources.append('DrugBank')
                                stats['DrugBank'] += 1
                                break
                        
                        # PubChem
                        for sub_id in med['substance_ref_ids']:
                            if sub_id in substance_to_pubchem:
                                sources.append('PubChem')
                                stats['PubChem'] += 1
                                break
                
                # 6. OpenFDA - à implémenter si disponible
                
                # Mise à jour uniquement si les sources ont changé
                current_sources = market.get('data_sources', [])
                if set(sources) != set(current_sources):
                    from pymongo import UpdateOne
                    bulk_operations.append(
                        UpdateOne(
                            {'_id': market['_id']},
                            {'$set': {'data_sources': sources}}
                        )
                    )
            
            # Exécuter le bulk update
            if bulk_operations:
                db.medicine_market.bulk_write(bulk_operations)
                updated_count += len(bulk_operations)
            
            skip += batch_size
            pbar.update(len(markets))
    
    print(f"\n✅ Terminé! {updated_count:,} documents mis à jour")
    print("\n📊 Statistiques par source:")
    for source, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {source:15} : {count:,} médocs")
    
    # Vérification
    print("\n🔍 Vérification...")
    sample = db.medicine_market.find_one({'data_sources': {'$exists': True}})
    if sample:
        print(f"  Exemple: {sample.get('brand_title')}")
        print(f"  Sources: {sample.get('data_sources')}")
    
    # Créer un index pour accélérer les recherches
    print("\n📇 Création de l'index sur data_sources...")
    db.medicine_market.create_index('data_sources')
    print("  ✅ Index créé")
    
    print("\n" + "=" * 100)
    print("💡 PRÊT POUR LA DÉMO!")
    print("=" * 100)
    print("""
    Vous pouvez maintenant:
    1. Filtrer par source dans l'API: ?sources=ANSM,PharmGKB
    2. Afficher des badges par source dans l'UI
    3. Montrer les statistiques par source
    """)

if __name__ == '__main__':
    start = time.time()
    main()
    print(f"\n⏱️  Temps d'exécution: {time.time() - start:.2f}s")
