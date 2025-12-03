"""
Ancien scraper remplacé par le pipeline Agno dans le dossier `scrapers/`.

Pour lancer un scraping ANSM :
    cd /chemin/vers/Medialise
    py -m scrapers.test_agno_pipeline

Pour importer les JSON vers Mongo :
    py -m scrapers.import_json_to_mongo
"""

if __name__ == "__main__":
    print(__doc__)