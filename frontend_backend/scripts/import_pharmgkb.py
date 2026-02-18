"""
Script pour importer les données PharmGKB dans MongoDB
Créé le: 2026-01-27
"""
import json
import sys
from pathlib import Path
from pymongo import MongoClient
import os

# Configuration MongoDB - utilise localhost si hors Docker, sinon mongo
MONGO_HOST = os.environ.get('MONGO_HOST', 'localhost')
MONGO_URI = f'mongodb://{MONGO_HOST}:27017/medicsearch'

def get_db():
    """Connexion à MongoDB"""
    client = MongoClient(MONGO_URI)
    return client.medicsearch

def import_pharmgkb_drugs():
    """Importe les médicaments PharmGKB dans MongoDB"""
    db = get_db()
    drugs_file = Path(__file__).parent.parent.parent / 'data' / 'pharmgkb' / 'medicsearch.pharmgkb_drugs.json'
    
    print(f"📂 Chargement du fichier: {drugs_file}")
    
    with open(drugs_file, 'r', encoding='utf-8') as f:
        drugs_data = json.load(f)
    
    print(f"📊 Nombre de médicaments PharmGKB: {len(drugs_data)}")
    
    # Supprimer la collection existante pour éviter les doublons
    db.pharmgkb_drugs.drop()
    
    # Préparer les données pour l'insertion
    for drug in drugs_data:
        # Retirer l'_id MongoDB existant pour laisser MongoDB en générer un nouveau
        if '_id' in drug and '$oid' in drug['_id']:
            del drug['_id']
    
    # Insérer les données
    if drugs_data:
        result = db.pharmgkb_drugs.insert_many(drugs_data)
        print(f"✅ {len(result.inserted_ids)} médicaments PharmGKB importés")
        
        # Créer un index sur pharmgkb_id pour des recherches rapides
        db.pharmgkb_drugs.create_index('pharmgkb_id')
        # Créer un index sur le nom pour les recherches textuelles
        db.pharmgkb_drugs.create_index('name')
        print("✅ Index créés sur pharmgkb_id et name")
    
    return len(drugs_data)

def import_pharmgkb_relationships():
    """Importe les relations pharmacogénomiques PharmGKB dans MongoDB"""
    db = get_db()
    rel_file = Path(__file__).parent.parent.parent / 'data' / 'pharmgkb' / 'medicsearch.pharmgkb_relationships.json'
    
    print(f"📂 Chargement du fichier: {rel_file}")
    
    with open(rel_file, 'r', encoding='utf-8') as f:
        relationships_data = json.load(f)
    
    print(f"📊 Nombre de relations pharmacogénomiques: {len(relationships_data)}")
    
    # Supprimer la collection existante pour éviter les doublons
    db.pharmgkb_relationships.drop()
    
    # Préparer les données pour l'insertion
    for rel in relationships_data:
        # Retirer l'_id MongoDB existant pour laisser MongoDB en générer un nouveau
        if '_id' in rel and '$oid' in rel['_id']:
            del rel['_id']
    
    # Insérer les données
    if relationships_data:
        result = db.pharmgkb_relationships.insert_many(relationships_data)
        print(f"✅ {len(result.inserted_ids)} relations pharmacogénomiques importées")
        
        # Créer des index pour des recherches rapides
        db.pharmgkb_relationships.create_index('pharmgkb_drug_id')
        db.pharmgkb_relationships.create_index('drug_name')
        db.pharmgkb_relationships.create_index('gene_symbol')
        print("✅ Index créés sur pharmgkb_drug_id, drug_name et gene_symbol")
    
    return len(relationships_data)

def main():
    """Fonction principale"""
    print("🚀 Début de l'importation des données PharmGKB\n")
    
    try:
        # Importer les médicaments
        drugs_count = import_pharmgkb_drugs()
        print()
        
        # Importer les relations
        rel_count = import_pharmgkb_relationships()
        print()
        
        print("=" * 60)
        print(f"✅ IMPORTATION TERMINÉE")
        print(f"   - {drugs_count} médicaments PharmGKB")
        print(f"   - {rel_count} relations pharmacogénomiques")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Erreur lors de l'importation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
