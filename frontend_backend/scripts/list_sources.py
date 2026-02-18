#!/usr/bin/env python3
"""Script pour lister toutes les sources de données disponibles"""

from pymongo import MongoClient

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    # Extraire la source depuis market_key (format: COUNTRY|SOURCE|ID)
    pipeline = [
        {
            '$project': {
                'source': {
                    '$arrayElemAt': [
                        {'$split': ['$market_key', '|']}, 
                        1
                    ]
                }
            }
        },
        {
            '$group': {
                '_id': '$source',
                'count': {'$sum': 1}
            }
        },
        {
            '$sort': {'count': -1}
        }
    ]
    
    sources = list(db.medicine_market.aggregate(pipeline))
    
    print('Sources de données disponibles dans medicine_market:')
    print('=' * 60)
    for source in sources:
        print(f'  - {source["_id"]}: {source["count"]} médicaments')
    print('=' * 60)
    print(f'Total: {len(sources)} sources')
    
    # Vérifier aussi dans medicines_v3
    print('\n\nExemples de medicine_key dans medicines_v3:')
    print('=' * 60)
    samples = list(db.medicines_v3.find({}, {'medicine_key': 1}).limit(10))
    for sample in samples:
        print(f'  - {sample.get("medicine_key")}')

if __name__ == '__main__':
    main()
