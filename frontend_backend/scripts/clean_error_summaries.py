#!/usr/bin/env python3
"""Supprimer les résumés d'erreur de la base de données"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client.medicsearch

# Rechercher les résumés contenant "Erreur: Clé API"
error_summaries_medicines = db.medicines.count_documents({
    "ai_summary": {"$regex": "Erreur: Clé API"}
})

error_summaries_market = db.medicine_market.count_documents({
    "ai_summary": {"$regex": "Erreur: Clé API"}
})

print(f"Résumés d'erreur dans medicines: {error_summaries_medicines}")
print(f"Résumés d'erreur dans medicine_market: {error_summaries_market}")
print()

if error_summaries_medicines > 0 or error_summaries_market > 0:
    print("🗑️  Suppression des résumés d'erreur...")
    
    result1 = db.medicines.update_many(
        {"ai_summary": {"$regex": "Erreur: Clé API"}},
        {"$unset": {"ai_summary": "", "summary_timestamp": ""}}
    )
    
    result2 = db.medicine_market.update_many(
        {"ai_summary": {"$regex": "Erreur: Clé API"}},
        {"$unset": {"ai_summary": "", "summary_timestamp": ""}}
    )
    
    print(f"✅ {result1.modified_count} résumés supprimés de medicines")
    print(f"✅ {result2.modified_count} résumés supprimés de medicine_market")
    print()
    print("Maintenant, rafraîchissez la page du médicament.")
    print("Le résumé sera régénéré automatiquement avec la bonne clé API.")
else:
    print("✅ Aucun résumé d'erreur trouvé")
