#!/usr/bin/env python3
"""Script pour supprimer le résumé d'erreur du médicament A313"""

from pymongo import MongoClient

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    # Supprimer le résumé d'erreur
    result = db.medicine_market.update_one(
        {'market_key': 'FR|BDPM|61266250'},
        {'$unset': {'ai_summary': ''}}
    )
    
    print(f'✅ Résumé supprimé: {result.modified_count} document(s) modifié(s)')
    
    # Vérifier
    doc = db.medicine_market.find_one({'market_key': 'FR|BDPM|61266250'}, {'ai_summary': 1, '_id': 1})
    if doc:
        print(f'📊 Document _id: {doc["_id"]}')
        print(f'📝 A un résumé: {"ai_summary" in doc}')
    else:
        print('❌ Document non trouvé')

if __name__ == '__main__':
    main()
