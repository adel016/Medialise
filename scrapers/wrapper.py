import sys
import os

# Récupère le chemin absolu du dossier scrapers/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Chemin vers frontend_backend/scripts où se trouve scraper.py
FRONTEND_BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "frontend_backend"))
SCRIPTS_DIR = os.path.join(FRONTEND_BACKEND_DIR, "scripts")

# Ajoute ces chemins au PYTHONPATH
sys.path.append(FRONTEND_BACKEND_DIR)
sys.path.append(SCRIPTS_DIR)

# Debug : vérifier si scraper.py existe bien
print(">> FRONTEND_BACKEND_DIR =", FRONTEND_BACKEND_DIR)
print(">> SCRIPTS_DIR =", SCRIPTS_DIR)
print(">> scraper.py exists? ", os.path.exists(os.path.join(SCRIPTS_DIR, "scraper.py")))

# Importer ton scraper original
from scripts.scraper import run_scraper

def run_scraper_full(max_urls=None):
    return run_scraper(
        db_connection=None,
        source_file=None,
        max_urls=max_urls
    )
