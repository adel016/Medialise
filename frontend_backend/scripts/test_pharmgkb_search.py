"""
Script de test pour vérifier la recherche PharmGKB
"""
import sys
from pathlib import Path
from pymongo import MongoClient
import os
import re

# Configuration MongoDB
MONGO_HOST = os.environ.get('MONGO_HOST', 'localhost')
MONGO_URI = f'mongodb://{MONGO_HOST}:27017/medicsearch'

def get_db():
    """Connexion à MongoDB"""
    client = MongoClient(MONGO_URI)
    return client.medicsearch

def clean_name(name):
    """Nettoie un nom de médicament pour la recherche"""
    if not name:
        return ""
    # Retirer les dosages, formes, etc.
    name = name.lower().strip()
    # Retirer les chiffres et mg, g, etc.
    name = re.sub(r'\d+\s*(mg|g|ml|%|ui|µg)\b', '', name)
    # Retirer les formes pharmaceutiques courantes
    name = re.sub(r'\b(comprimé|gélule|solution|injectable|poudre|suspension|sirop|crème|pommade|gel)\b', '', name)
    # Retirer les formes chimiques (monohydrate, chlorhydrate, etc.)
    name = re.sub(r'\b(monohydrate|dihydrate|trihydrate|chlorhydrate|sulfate|phosphate|citrate|succinate|fumarate|malate|tartrate|lactate|gluconate|carbonate|nitrate)\b', '', name)
    # Retirer les virgules et "pour"
    name = re.sub(r'[,\-]', ' ', name)
    name = re.sub(r'\bpour\b', ' ', name)
    # Nettoyer les espaces multiples
    name = ' '.join(name.split())
    return name.strip()

def test_search(medicine_name, substances_actives=None):
    """Teste la recherche PharmGKB"""
    db = get_db()
    
    print(f"\n{'='*60}")
    print(f"🔍 Test de recherche pour: {medicine_name}")
    if substances_actives:
        print(f"   Substances actives: {substances_actives}")
    print(f"{'='*60}")
    
    # Collecter tous les noms à rechercher
    search_names = set()
    
    # Ajouter le nom du médicament (nettoyé et original)
    cleaned_medicine_name = clean_name(medicine_name)
    if cleaned_medicine_name:
        search_names.add(cleaned_medicine_name)
        first_word = cleaned_medicine_name.split()[0] if cleaned_medicine_name.split() else ""
        if first_word and len(first_word) > 3:
            search_names.add(first_word)
    
    # Ajouter les substances actives
    if substances_actives:
        for substance in substances_actives:
            if isinstance(substance, dict):
                sub_name = substance.get('nom', '').lower().strip()
            elif isinstance(substance, str):
                sub_name = substance.lower().strip()
            else:
                continue
            
            if sub_name and len(sub_name) > 2:
                search_names.add(sub_name)
                cleaned_sub = clean_name(sub_name)
                if cleaned_sub and cleaned_sub != sub_name:
                    search_names.add(cleaned_sub)
    
    print(f"\n📝 Noms de recherche: {list(search_names)}")
    
    # Chercher
    for name in search_names:
        if not name or len(name) < 3:
            continue
        
        print(f"\n🔎 Recherche de: '{name}'")
        
        # Essayer correspondance exacte
        drug = db.pharmgkb_drugs.find_one({'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}})
        if drug:
            print(f"   ✅ Trouvé (exacte): {drug.get('name')} (ID: {drug.get('pharmgkb_id')})")
            
            # Compter les relations
            rel_count = db.pharmgkb_relationships.count_documents({'pharmgkb_drug_id': drug.get('pharmgkb_id')})
            print(f"   📊 {rel_count} relations pharmacogénomiques")
            
            # Afficher quelques gènes
            rels = list(db.pharmgkb_relationships.find({'pharmgkb_drug_id': drug.get('pharmgkb_id')}).limit(5))
            genes = [r.get('gene_symbol') for r in rels if r.get('gene_symbol')]
            if genes:
                print(f"   🧬 Exemples de gènes: {', '.join(genes[:5])}")
            
            return True
        
        # Essayer correspondance partielle
        drug = db.pharmgkb_drugs.find_one({'name': {'$regex': re.escape(name), '$options': 'i'}})
        if drug:
            print(f"   ✅ Trouvé (partielle): {drug.get('name')} (ID: {drug.get('pharmgkb_id')})")
            return True
        
        # Chercher dans synonymes
        drug = db.pharmgkb_drugs.find_one({'synonyms': {'$regex': re.escape(name), '$options': 'i'}})
        if drug:
            print(f"   ✅ Trouvé (synonyme): {drug.get('name')} (ID: {drug.get('pharmgkb_id')})")
            return True
        
        # Chercher via relationships
        rel = db.pharmgkb_relationships.find_one({'drug_name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}})
        if rel:
            drug = db.pharmgkb_drugs.find_one({'pharmgkb_id': rel.get('pharmgkb_drug_id')})
            if drug:
                print(f"   ✅ Trouvé (via relationship): {drug.get('name')} (ID: {drug.get('pharmgkb_id')})")
                return True
        
        print(f"   ❌ Non trouvé pour '{name}'")
    
    print(f"\n❌ Aucune correspondance trouvée dans PharmGKB")
    return False

def main():
    print("🚀 Test de recherche PharmGKB\n")
    
    # Test 1: ENDOXAN avec cyclophosphamide
    test_search(
        "ENDOXAN 1000 mg, poudre pour solution injectable",
        substances_actives=[
            {"nom": "CYCLOPHOSPHAMIDE MONOHYDRATE"}
        ]
    )
    
    # Test 2: Paracétamol
    test_search(
        "DOLIPRANE 1000 mg, comprimé",
        substances_actives=[
            {"nom": "PARACETAMOL"}
        ]
    )
    
    # Test 3: Imatinib
    test_search(
        "GLIVEC 100 mg, comprimé pelliculé",
        substances_actives=[
            {"nom": "IMATINIB"}
        ]
    )

if __name__ == '__main__':
    main()
