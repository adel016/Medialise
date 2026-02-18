#!/usr/bin/env python3
"""Vérifier quel médicament a un résumé dans la base"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client.medicsearch

# Trouver un médicament avec résumé
med_with_summary = db.medicines.find_one({"ai_summary": {"$exists": True}})

if med_with_summary:
    print(f"✅ Médicament avec résumé trouvé :")
    print(f"   ID: {med_with_summary['_id']}")
    print(f"   Titre: {med_with_summary.get('title', med_with_summary.get('name', 'N/A'))}")
    print(f"   Résumé: {med_with_summary.get('ai_summary', '')[:100]}...")
    print()
    print(f"URL de test: http://localhost:5000/medicine/{med_with_summary['_id']}")
else:
    print("❌ Aucun médicament avec résumé trouvé")
    print()
    print("Médicaments disponibles:")
    for i, med in enumerate(db.medicines.find().limit(5)):
        print(f"  {i+1}. ID: {med['_id']} - {med.get('title', med.get('name', 'N/A'))}")
