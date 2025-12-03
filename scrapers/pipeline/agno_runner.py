import json
import os
from datetime import datetime
from scrapers.agno_agent import Agent
from scrapers.sources.ansm_html import scrape_html
import pandas as pd                      # ← ajout


# Dossier de sortie
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_urls_from_excel(max_urls: int | None = None):
    """
    Charge les URLs depuis scripts/liens_R.xlsx (colonne 'liens').

    Dans le conteneur Docker, le projet est sous /app et le fichier est
    /app/scripts/liens_R.xlsx.
    En local, si tu lances depuis la racine du projet, c'est aussi valable.
    """
    # 1) Chemin absolu Docker /app/scripts/liens_R.xlsx
    excel_path = "/app/scripts/liens_R.xlsx"

    # 2) Si on est en local hors Docker, /app n'existe pas.
    #    On retombe alors sur le chemin relatif depuis ce fichier.
    if not os.path.exists(excel_path):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        excel_path = os.path.join(project_root, "frontend_backend", "scripts", "liens_R.xlsx")

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Fichier Excel introuvable : {excel_path}")

    print(f"Chargement des URLs depuis : {excel_path}")
    df = pd.read_excel(excel_path, engine="openpyxl")

    if "liens" not in df.columns:
        raise ValueError("La colonne 'liens' est manquante dans liens_R.xlsx")

    urls = [str(u).strip() for u in df["liens"].tolist() if isinstance(u, str) and u.strip()]
    if max_urls is not None and max_urls > 0:
        urls = urls[:max_urls]

    print(f"{len(urls)} URLs chargées depuis l'Excel")
    return urls

# Agent Agno de test
class ANSMScrapingAgent(Agent):
    def run(self, url: str):
        """Appelle directement ta fonction scrape_html"""
        try:
            result = scrape_html(url)
            return {
                "url": url,
                "status": "success",
                "data": result
            }
        except Exception as e:
            return {
                "url": url,
                "status": "error",
                "error": str(e)
            }

def run_agno_test(urls=None, limit: int | None = None):
    """
    Exécute un test Agno sur plusieurs URLs et sauvegarde en JSON.

    - si urls est None : lit les URLs dans liens_R.xlsx
    - limit permet de limiter le nombre d’URLs pour les tests
    """
    if urls is None:
        # on charge depuis l'Excel, en appliquant éventuellement limit
        urls = load_urls_from_excel(max_urls=limit)
    elif limit is not None and limit > 0:
        urls = urls[:limit]

    total = len(urls)
    print(f"{total} URLs à traiter via Agno.")

    agent = ANSMScrapingAgent()
    results = []

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{total}] Scraping via Agno → {url}")
        try:
            result = agent.run(url)
            results.append(result)
            print(f"[{i}/{total}] Statut: {result.get('status')}")
        except Exception as e:
            print(f"[{i}/{total}] ERREUR pendant le scraping de {url} : {e!r}")

    # Sauvegarde JSON
    output_file = os.path.join(
        OUTPUT_DIR,
        f"agno_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n=== TEST TERMINÉ ===")
    print(f"→ Résultats sauvegardés dans : {output_file}")
    print(f"{len(results)} résultats au total.")
    return output_file
