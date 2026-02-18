#!/usr/bin/env python3
"""
Script de test rapide pour vérifier la génération de résumé IA
"""
import sys
from pathlib import Path

# Ajouter le chemin du frontend_backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import MongoClient
from bson import ObjectId

# Configuration MongoDB
MONGO_URI = "mongodb://localhost:27017"
client = MongoClient(MONGO_URI)
db = client.medicsearch

# Charger ai_summary
from ai_summary import get_or_generate_summary

def test_summary_generation():
    """Teste la génération d'un résumé pour un médicament"""
    
    # Récupérer un médicament au hasard
    medicine = db.medicines.find_one()
    
    if not medicine:
        print("❌ Aucun médicament trouvé dans la base de données")
        return
    
    medicine_id = medicine.get('_id')
    medicine_name = medicine.get('title', medicine.get('name', 'Inconnu'))
    
    print(f"📋 Médicament sélectionné : {medicine_name}")
    print(f"🆔 ID : {medicine_id}")
    print()
    
    # Vérifier si un résumé existe déjà
    existing_summary = medicine.get('ai_summary')
    
    if existing_summary:
        print("✅ Résumé existant trouvé :")
        print(existing_summary[:200] + "...")
        print()
        print("🗑️  Suppression du résumé existant pour tester la génération...")
        db.medicines.update_one(
            {"_id": medicine_id},
            {"$unset": {"ai_summary": "", "summary_timestamp": ""}}
        )
        print("✅ Résumé supprimé")
        print()
    
    # Générer un nouveau résumé
    print("🤖 Génération d'un nouveau résumé...")
    try:
        summary = get_or_generate_summary(medicine, db=db)
        print()
        print("=" * 60)
        print("✅ RÉSUMÉ GÉNÉRÉ AVEC SUCCÈS !")
        print("=" * 60)
        print()
        print(summary)
        print()
        print("=" * 60)
        
        # Vérifier que le résumé a été sauvegardé
        updated_medicine = db.medicines.find_one({"_id": medicine_id})
        if updated_medicine.get('ai_summary'):
            print("✅ Résumé sauvegardé dans la base de données")
        else:
            print("⚠️  Résumé non sauvegardé dans la base de données")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la génération : {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("TEST DE GÉNÉRATION DE RÉSUMÉ IA")
    print("=" * 60)
    print()
    
    success = test_summary_generation()
    
    print()
    if success:
        print("🎉 Test réussi !")
        print()
        print("Maintenant, testez dans l'application web :")
        print("1. Lancez l'application Flask")
        print("2. Naviguez vers un médicament")
        print("3. Le résumé devrait s'afficher automatiquement")
    else:
        print("❌ Test échoué")
        print("Vérifiez les logs ci-dessus pour plus de détails")
