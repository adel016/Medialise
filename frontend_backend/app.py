from ai_summary import get_or_generate_summary, call_mistral_reformulate, call_mistral_summarize
# --- Initialisation Flask et Qdrant ---

from flask import Flask, request, render_template, jsonify, abort, redirect, url_for, stream_with_context, Response, session, g
from flask_babel import Babel, gettext, get_locale
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from bson import json_util
import time
import hashlib
from functools import lru_cache
import os
import datetime
import re
from models import init_db, mongo, User
import users  # Importer le module users complet
from users import role_required  # Importer la fonction spécifique role_required
from config import get_config
# Import the AI summary module
from ai_summary import get_or_generate_summary
from pymongo.errors import ServerSelectionTimeoutError
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import Counter
from flask import render_template_string
from bson.objectid import ObjectId


# --- Initialisation Flask et Qdrant ---
app = Flask(__name__)
# Charger la configuration

app_config = get_config()
app.config.from_object(app_config)

# Définir MONGO_DB aussi si nécessaire (flask-pymongo l'utilise)
if 'MONGO_DB' not in app.config:
    app.config['MONGO_DB'] = 'medicsearch'

# Configuration de Babel pour l'internationalisation
app.config['BABEL_DEFAULT_LOCALE'] = 'fr'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'
app.config['LANGUAGES'] = {
    'fr': {'name': 'Français', 'flag': '🇫🇷'},
    'en': {'name': 'English', 'flag': '🇬🇧'},
    'ar': {'name': 'العربية', 'flag': '🇸🇦'}
}

babel = Babel(app)

def get_locale():
    """Détermine la langue à utiliser pour l'utilisateur"""
    # 1. Vérifier si la langue est stockée dans la session
    if 'language' in session:
        return session['language']
    # 2. Utiliser la langue du navigateur
    return request.accept_languages.best_match(app.config['LANGUAGES'].keys())

babel.init_app(app, locale_selector=get_locale)

qdrant_client = QdrantClient(app.config['QDRANT_HOST'], port=app.config['QDRANT_PORT'])
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def wait_for_mongo(uri, timeout=30):
    """Attend que Mongo soit joignable avant de continuer."""
    start = time.time()
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    while True:
        try:
            client.admin.command("ping")
            print("MongoDB est prêt.")
            client.close()
            return
        except ServerSelectionTimeoutError:
            if time.time() - start > timeout:
                client.close()
                raise
            print("MongoDB pas encore prêt, nouvelle tentative...")
            time.sleep(2)

# Attendre Mongo AVANT init_db
wait_for_mongo(app.config["MONGO_URI"])

# Important: Initialiser la base de données avant d'accéder à mongo.db
init_db(app)

# Utiliser mongo.db pour accéder à la base de données MongoDB après l'initialisation
db = mongo.db
app.db = db

# --- Collections V3 ---
medicines_v3 = db["medicines_v3"]
substances_v3 = db["substances_v3"]
medicine_market = db["medicine_market"]

# IMPORTANT:
# - on garde "collection" pour compatibilité avec le reste du code (recherche classique, détails, etc.)
# - on pointe maintenant sur medicines_v3
collection = medicines_v3

# Fonction pour convertir les objets BSON en JSON serializable
def bson_to_json(data):
    """Convertit les objets BSON en dictionnaires JSON serialisables"""
    return json.loads(json_util.dumps(data))

# Fonction pour extraire le nom du médicament
def extract_medicine_name(medicine):
    return get_display_title(medicine)

def get_display_title(med: dict) -> str:
    # v2
    if med.get("drug", {}).get("full_title"):
        return med["drug"]["full_title"]
    if med.get("drug", {}).get("name"):
        return med["drug"]["name"]
    # v1
    if med.get("title"):
        return med["title"]
    return f"Médicament {med.get('_id')}"

def get_update_date(med: dict) -> str:
    # v2 (si tu veux afficher une date stable)
    upd = med.get("document", {}).get("updated_at")
    if upd:
        try:
            # upd peut être datetime déjà
            return upd.strftime("%Y-%m-%d")
        except Exception:
            return str(upd)
    # v1
    return med.get("update_date", "Non disponible")


@app.route('/')
def index():
    # --- V3 collections ---
    db = mongo.db
    medicines_v3 = db["medicines_v3"]
    substances_v3 = db["substances_v3"]
    medicine_market = db["medicine_market"]

    # 1) Total "médocs réels" = lignes market
    total_medicines = medicine_market.count_documents({})

    # 2) Substances (V3)
    substance_count = substances_v3.count_documents({})

    # 3) Laboratoires (market a un champ laboratory propre)
    # distinct sur market => plus fiable que de deviner un champ dans medicines_v3
    lab_count = len(medicine_market.distinct("laboratory", {"laboratory": {"$nin": [None, ""]}}))

    # 4) Répartition par pays (top 8)
    pipeline_countries = [
        {"$match": {"country": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$country", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 8}
    ]
    countries_stats = list(medicine_market.aggregate(pipeline_countries))
    # format: [{"country":"FR","count":7749}, ...]
    countries_stats = [{"country": d["_id"], "count": d["count"]} for d in countries_stats]

    max_country_count = countries_stats[0]["count"] if countries_stats else 1


    # 5) Présence des sources (d’après source_urls)
    # On compte combien de docs market contiennent une URL qui match un domaine
    source_patterns = {
        "ANSM/BDPM": "base-donnees-publique.medicaments.gouv.fr",
        "Thériaque": "theriaque",
        "DrugBank": "drugbank",
        "PubChem": "pubchem",
        "OpenFDA": "openfda",
    }

    sources_stats = []
    for label, pattern in source_patterns.items():
        c = medicine_market.count_documents({"source_urls": {"$elemMatch": {"$regex": pattern, "$options": "i"}}})
        sources_stats.append({"source": label, "count": c})

    # 6) Petit bloc “latest” : derniers ajouts market (utile sur home)
    latest_market = list(
        medicine_market.find(
            {},
            {"_id": 1, "brand_title": 1, "country": 1, "laboratory": 1, "cis": 1, "updated_at": 1}
        ).sort([("updated_at", -1)]).limit(5)
    )

    return render_template(
        "index.html",
        total_medicines=total_medicines,
        lab_count=lab_count,
        substance_count=substance_count,
        countries_stats=countries_stats,
        sources_stats=sources_stats,
        latest_market=latest_market,
        max_country_count=max_country_count,
    )


@app.route('/test-v3')
def test_v3():
    """Page de test pour la nouvelle architecture V3"""
    return render_template("test_v3.html")


# ───────────────────────────────────────────────────────────────────
# Grossesse / Allaitement / Pédiatrie — classification depuis RCP 4.6
# ───────────────────────────────────────────────────────────────────
def _extract_section_46_text(rcp: dict) -> dict:
    """
    Extrait le texte brut des sous-sections Grossesse, Allaitement et Fertilité
    depuis la section RCP 4.6. Renvoie un dict {grossesse, allaitement, fertilite}
    avec le texte concaténé de chaque sous-section.
    """
    result = {"grossesse": "", "allaitement": "", "fertilite": "", "raw": ""}
    if not rcp or not isinstance(rcp, dict):
        return result

    sections = rcp.get("sections") or []
    for section in sections:
        title = (section.get("title") or "").strip()
        if not title.startswith("4.") and "DONNEES CLINIQUES" not in title.upper():
            continue

        subsections = section.get("subsections") or []
        for sub in subsections:
            sub_title = (sub.get("title") or "").lower()
            if "4.6" not in sub_title and "grossesse" not in sub_title and "fertil" not in sub_title:
                continue

            # Texte direct de la section 4.6
            raw_parts = []
            for c in (sub.get("content") or []):
                txt = (c.get("text") or "").strip() if isinstance(c, dict) else str(c).strip()
                if txt:
                    raw_parts.append(txt)

            # Sous-sous-sections (Grossesse, Allaitement, Fertilité)
            for subsub in (sub.get("subsections") or []):
                ss_title = (subsub.get("title") or "").lower().strip()
                ss_parts = []
                for c in (subsub.get("content") or []):
                    txt = (c.get("text") or "").strip() if isinstance(c, dict) else str(c).strip()
                    if txt:
                        ss_parts.append(txt)
                ss_text = " ".join(ss_parts)

                if "grossesse" in ss_title:
                    result["grossesse"] += " " + ss_text
                elif "allaitement" in ss_title:
                    result["allaitement"] += " " + ss_text
                elif "fertil" in ss_title:
                    result["fertilite"] += " " + ss_text
                else:
                    raw_parts.append(ss_text)

            combined_raw = " ".join(raw_parts)
            result["raw"] += " " + combined_raw

            # Si pas de sous-sous-sections étiquetées, tout mettre dans grossesse+allaitement
            if not result["grossesse"] and not result["allaitement"]:
                full = combined_raw.lower()
                result["grossesse"] = combined_raw
                result["allaitement"] = combined_raw

            break  # section 4.6 trouvée
    return result


def _classify_text_pregnancy(text: str) -> str:
    """
    Classifie un texte RCP grossesse/allaitement.
    Renvoie: 'danger', 'deconseille', 'precaution', 'ok', 'unknown'
    """
    if not text or not text.strip():
        return "unknown"
    t = text.lower()

    # DANGER — contre-indiqué
    danger_kw = [
        "contre-indiqué", "contre-indiquée", "contre-indiquées", "contre-indiqués",
        "ne doit pas être utilisé", "ne doit pas être administré",
        "ne pas utiliser", "formellement contre-indiqué",
        "est interdit", "interdite pendant la grossesse",
        "est contre-indiqué pendant", "usage est contre-indiqué",
    ]
    for kw in danger_kw:
        if kw in t:
            return "danger"

    # DÉCONSEILLÉ
    deconseille_kw = [
        "déconseillé", "est déconseillée", "ne doit être envisagé",
        "ne doit être utilisé que si", "ne doit pas être prescrit",
        "éviter", "doit être évité",
        "ne pas allaiter", "n'est pas recommandé",
    ]
    for kw in deconseille_kw:
        if kw in t:
            return "deconseille"

    # PRÉCAUTION — ni interdit ni déconseillé mais attention
    precaution_kw = [
        "précaution", "prudence", "si nécessaire",
        "après évaluation du rapport bénéfice", "bénéfice/risque",
        "sous surveillance", "avis médical",
        "données limitées", "données insuffisantes",
        "pas de données adéquates", "par mesure de précaution",
    ]
    for kw in precaution_kw:
        if kw in t:
            return "precaution"

    # OK — explicitement compatible
    ok_kw = [
        "peut être utilisé", "peut être poursuivi",
        "compatible avec", "sans risque",
        "peut être administré", "peut être pris",
        "n'a pas montré de risque", "absence de risque",
    ]
    for kw in ok_kw:
        if kw in t:
            return "ok"

    return "unknown"


def classify_pregnancy_breastfeeding(rcp: dict) -> dict:
    """
    Analyse la section 4.6 du RCP et classifie les risques pour :
      - grossesse
      - allaitement
      - fertilité
    Renvoie un dict avec le niveau de risque et un court résumé.
    Niveaux: danger / deconseille / precaution / ok / unknown
    """
    texts = _extract_section_46_text(rcp)

    grossesse_text = texts["grossesse"] or texts["raw"]
    allaitement_text = texts["allaitement"] or texts["raw"]
    fertilite_text = texts["fertilite"]

    result = {
        "grossesse": {
            "level": _classify_text_pregnancy(grossesse_text),
            "text": grossesse_text.strip()[:300] if grossesse_text.strip() else "",
        },
        "allaitement": {
            "level": _classify_text_pregnancy(allaitement_text),
            "text": allaitement_text.strip()[:300] if allaitement_text.strip() else "",
        },
        "fertilite": {
            "level": _classify_text_pregnancy(fertilite_text),
            "text": fertilite_text.strip()[:300] if fertilite_text.strip() else "",
        },
        "has_data": bool(grossesse_text.strip() or allaitement_text.strip()),
    }

    # Niveau global = le pire des 3
    levels_order = {"danger": 0, "deconseille": 1, "precaution": 2, "ok": 3, "unknown": 4}
    worst = min(
        [result["grossesse"]["level"], result["allaitement"]["level"]],
        key=lambda x: levels_order.get(x, 5)
    )
    result["global_level"] = worst

    return result


def extract_filter_options():
    """
    Filtres pour la recherche classique (V3).
    - substances: depuis substances_v3.label
    - formes/lab/dosages/countries: depuis medicine_market
    """
    cached = getattr(extract_filter_options, "_cache", None)
    if cached:
        return cached

    try:
        substances = substances_v3.distinct("label", {"label": {"$nin": [None, ""]}})
        formes = medicine_market.distinct("form", {"form": {"$nin": [None, ""]}})
        laboratoires = medicine_market.distinct("laboratory", {"laboratory": {"$nin": [None, ""]}})
        dosages = medicine_market.distinct("strength", {"strength": {"$nin": [None, ""]}})
        countries = medicine_market.distinct("country", {"country": {"$nin": [None, ""]}})

        result = {
            "substances": sorted([s for s in substances if isinstance(s, str) and s.strip()]),
            "formes": sorted([f for f in formes if isinstance(f, str) and f.strip()]),
            "laboratoires": sorted([l for l in laboratoires if isinstance(l, str) and l.strip()]),
            "dosages": sorted([d for d in dosages if isinstance(d, str) and d.strip()]),
            "countries": sorted([c for c in countries if isinstance(c, str) and c.strip()]),
        }

        extract_filter_options._cache = result
        return result

    except Exception as e:
        print(f"[extract_filter_options V3] erreur: {e}")
        return {"substances": [], "formes": [], "laboratoires": [], "dosages": [], "countries": []}


def infer_source_tags(market_doc, med_doc):
    tags = set()

    # market: URLs -> BDPM/ANSM (RCP) en France
    for u in (market_doc.get("source_urls") or []):
        if not isinstance(u, str):
            continue
        ul = u.lower()
        if "base-donnees-publique.medicaments.gouv.fr" in ul:
            tags.add("BDPM/ANSM")

    # substances: pubchem/drugbank
    # (souvent présent via medicines_v3.substance_ref_ids -> substances_v3, mais ici on check med_doc si tu y stockes)
    # On ne peut pas accéder à substances_v3 ici sans map, donc on renverra aussi "has_pubchem/drugbank" depuis la boucle plus bas
    return sorted(tags)



def extract_filter_options_from_results(medicines):
    """Extrait les options de filtre disponibles uniquement à partir des résultats actuels"""
    # Initialiser les ensembles pour stocker les valeurs uniques
    substances_actives = set()
    formes_pharma = set()
    laboratoires = set()
    dosages = set()
    
    # Parcourir les résultats de recherche actuels
    for medicine in medicines:
        # Extraction depuis medicine_details
        if 'medicine_details' in medicine:
            # Substances actives
            if 'substances_actives' in medicine['medicine_details'] and medicine['medicine_details']['substances_actives']:
                for substance in medicine['medicine_details']['substances_actives']:
                    if substance and len(substance) > 2:  # Ignorer les valeurs trop courtes
                        substances_actives.add(substance)
            
            # Formes pharmaceutiques
            if 'forme' in medicine['medicine_details'] and medicine['medicine_details']['forme']:
                forme = medicine['medicine_details']['forme']
                if forme and len(forme) > 2:  # Ignorer les valeurs trop courtes
                    formes_pharma.add(forme)
            
            # Laboratoires
            if 'laboratoire' in medicine['medicine_details'] and medicine['medicine_details']['laboratoire']:
                laboratoire = medicine['medicine_details']['laboratoire']
                if laboratoire and len(laboratoire) > 2:
                    laboratoires.add(laboratoire)
            
            # Dosages
            if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
                for dosage in medicine['medicine_details']['dosages']:
                    if dosage and len(str(dosage)) > 1:
                        dosages.add(dosage)
    
    # Convertir en listes triées
    result = {
        'substances': sorted(list(substances_actives)),
        'formes': sorted(list(formes_pharma)),
        'laboratoires': sorted(list(laboratoires)),
        'dosages': sorted(list(dosages))
    }
    
    return result

@app.route('/search')
def search():
    # Récupérer les paramètres pour les passer au template
    search_query = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    substance = request.args.get('substance', '')
    forme = request.args.get('forme', '')
    laboratoire = request.args.get('laboratoire', '')
    dosage = request.args.get('dosage', '')
    # Tri par défaut toujours alphabétique (A-Z)
    sort_option = request.args.get('sort', 'name_asc')
    advanced_search = substance or forme or laboratoire or dosage or sort_option != 'name_asc'
    
    # Get filter options
    available_filters = extract_filter_options()

    # Rendre le template sans les résultats
    return render_template('classic_search.html',
                          search=search_query,
                          substance=substance,
                          forme=forme,
                          laboratoire=laboratoire,
                          dosage=dosage,
                          sort=sort_option,
                          advanced_search=advanced_search,
                          current_page=page,
                          per_page=per_page,
                          available_filters=available_filters)

@lru_cache(maxsize=1024)
def convert_french_date_cached(date_str):
    """Version mise en cache de la conversion de date française"""
    if not date_str or not isinstance(date_str, str):
        return 0
    
    try:
        if '/' in date_str:
            day, month, year = map(int, date_str.split('/'))
            # Retourner une clé de tri au format AAAAMMJJ
            return year * 10000 + month * 100 + day
    except (ValueError, AttributeError):
        return 0
    return 0

def sort_medicines_by_date(medicines, sort_direction):
    """Trie les médicaments par date au format français (JJ/MM/AAAA)"""
    sort_start_time = time.time()
    
    def convert_french_date(medicine):
        # Vérifier si update_date existe dans le document
        if 'update_date' not in medicine:
            return 0
        
        # Utiliser la version mise en cache de la conversion
        return convert_french_date_cached(medicine['update_date'])
    
    # Utiliser la fonction de conversion pour trier
    sorted_medicines = sorted(
        medicines, 
        key=convert_french_date,
        reverse=(sort_direction == -1)  # True si sort_direction est -1 (descendant)
    )
    
    sort_duration = time.time() - sort_start_time
    print(f"TRI PAR DATE: {len(medicines)} documents triés en {sort_duration:.3f} secondes")
    
    return sorted_medicines

def calculate_relevance_score(medicine, search_query):
    """Calcule un score de pertinence pour le classement des résultats."""
    score = 0
    search_terms = search_query.lower().split()
    total_matches = 0  # Compteur pour le nombre total de correspondances
    
    # Si le terme de recherche est dans le titre (très important)
    if 'title' in medicine:
        title = medicine['title'].lower()
        for term in search_terms:
            term_count = title.count(term)
            if term_count > 0:
                score += 10 * term_count
                total_matches += term_count
                # Si c'est un match exact du titre, c'est encore mieux
                if title == term:
                    score += 15
    
    # Si le terme est dans les substances actives (important)
    if 'medicine_details' in medicine and 'substances_actives' in medicine['medicine_details']:
        for substance in medicine['medicine_details']['substances_actives']:
            substance_lower = substance.lower() if substance else ""
            for term in search_terms:
                term_count = substance_lower.count(term)
                if term_count > 0:
                    score += 8 * term_count
                    total_matches += term_count
                    # Match exact de la substance active
                    if substance_lower == term:
                        score += 10
    
    # Si le terme est dans la forme pharmaceutique ou le dosage (moyennement important)
    if 'medicine_details' in medicine:
        if 'forme' in medicine['medicine_details']:
            forme_lower = medicine['medicine_details']['forme'].lower()
            for term in search_terms:
                term_count = forme_lower.count(term)
                if term_count > 0:
                    score += 5 * term_count
                    total_matches += term_count
        
        if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
            for dosage in medicine['medicine_details']['dosages']:
                dosage_lower = str(dosage).lower() if dosage else ""
                for term in search_terms:
                    term_count = dosage_lower.count(term)
                    if term_count > 0:
                        score += 5 * term_count
                        total_matches += term_count
    
    # Si le terme est dans le contenu (moins important)
    if 'sections' in medicine:
        for section in medicine['sections']:
            section_importance = 0
            # Les sections avec des informations importantes ont un poids plus élevé
            important_sections = ["1. DENOMINATION DU MEDICAMENT", "2. COMPOSITION QUALITATIVE ET QUANTITATIVE"]
            
            # Vérifier le titre de la section
            section_title_lower = section['title'].lower()
            for term in search_terms:
                term_count = section_title_lower.count(term)
                if term_count > 0:
                    score += (2 + section_importance) * term_count
                    total_matches += term_count
            
            if section.get("content"):
                for item in section["content"]:
                    # Cas 1 : content = ["ligne", "ligne2", ...]
                    if isinstance(item, str) and item.strip():
                        text_lower = item.lower()
                    # Cas 2 : content = [{"text": "..."}, ...] (si ça existe dans certains docs)
                    elif isinstance(item, dict) and item.get("text"):
                        text_lower = str(item["text"]).lower()
                    else:
                        continue

                    for term in search_terms:
                        term_count = text_lower.count(term)
                        if term_count > 0:
                            score += (1 + section_importance) * term_count
                            total_matches += term_count

            # Chercher dans les sous-sections
            if 'subsections' in section:
                for subsection in section['subsections']:
                    # Vérifier le titre de la sous-section
                    subsection_title = subsection.get('title', '')
                    subsection_title_lower = subsection_title.lower()
                    for term in search_terms:
                        term_count = subsection_title_lower.count(term)
                        if term_count > 0:
                            score += 2 * term_count
                            total_matches += term_count
                    
                    if subsection.get("content"):
                        for item in subsection["content"]:
                            # Cas EMA PDF: liste de strings
                            if isinstance(item, str) and item.strip():
                                text_lower = item.lower()
                            # Cas HTML éventuel: liste de dicts {"text": ...}
                            elif isinstance(item, dict) and item.get("text"):
                                text_lower = str(item["text"]).lower()
                            else:
                                continue

                            for term in search_terms:
                                term_count = text_lower.count(term)
                                if term_count > 0:
                                    score += 1 * term_count
                                    total_matches += term_count

    # Ajouter le nombre total de correspondances au score pour qu'il compte dans le tri
    score += total_matches
    
    # Stocker le nombre de correspondances dans l'objet médicament pour l'affichage
    medicine['match_count'] = total_matches
    
    return score

def find_search_term_locations(medicine, search_query):
    """Identifie les endroits où les termes de recherche ont été trouvés dans un médicament, sans doublons visuels."""
    if not search_query:
        return []

    matches_dict = {}
    search_terms = search_query.lower().split()

    def add_match(location, text, term, count, priority):
        key = (location, term)
        if key in matches_dict:
            matches_dict[key]['count'] += count
            # On ne remplace pas l'extrait, on garde le premier
        else:
            matches_dict[key] = {
                'location': location,
                'text': text,  # Premier extrait rencontré
                'term': term,
                'count': count,
                'priority': priority
            }

    # Vérifier dans le titre
    if 'title' in medicine:
        title_lower = medicine['title'].lower()
        for term in search_terms:
            if term in title_lower:
                term_count = title_lower.count(term)
                add_match('Titre', medicine['title'], term, term_count, 1)

    # Vérifier dans les détails du médicament
    if 'medicine_details' in medicine:
        # Chercher dans substances_actives
        if 'substances_actives' in medicine['medicine_details'] and medicine['medicine_details']['substances_actives']:
            for substance in medicine['medicine_details']['substances_actives']:
                substance_lower = substance.lower() if substance else ""
                for term in search_terms:
                    if term in substance_lower:
                        term_count = substance_lower.count(term)
                        add_match('Substance active', substance, term, term_count, 2)

        # Chercher dans laboratoire
        if 'laboratoire' in medicine['medicine_details'] and medicine['medicine_details']['laboratoire']:
            lab_lower = medicine['medicine_details']['laboratoire'].lower()
            for term in search_terms:
                if term in lab_lower:
                    term_count = lab_lower.count(term)
                    add_match('Laboratoire', medicine['medicine_details']['laboratoire'], term, term_count, 3)

        # Chercher dans forme
        if 'forme' in medicine['medicine_details'] and medicine['medicine_details']['forme']:
            forme_lower = medicine['medicine_details']['forme'].lower()
            for term in search_terms:
                if term in forme_lower:
                    term_count = forme_lower.count(term)
                    add_match('Forme pharmaceutique', medicine['medicine_details']['forme'], term, term_count, 3)

        # Chercher dans dosages
        if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
            for dosage in medicine['medicine_details']['dosages']:
                dosage_str = str(dosage).lower() if dosage else ""
                for term in search_terms:
                    if term in dosage_str:
                        term_count = dosage_str.count(term)
                        add_match('Dosage', str(dosage), term, term_count, 3)

    # Chercher dans le contenu des sections
    if 'sections' in medicine and medicine['sections']:
        important_sections = ["1. DENOMINATION DU MEDICAMENT", "2. COMPOSITION QUALITATIVE ET QUANTITATIVE"]

        for section in medicine['sections']:
            if not isinstance(section, dict):
                continue

            section_importance = 0

            # ✅ titre de section en mode safe
            section_title = section.get('title', '')
            if section_title in important_sections:
                section_importance = 3

            section_title_lower = section_title.lower()
            for term in search_terms:
                term_count = section_title_lower.count(term)
                if term_count > 0:
                    score += (2 + section_importance) * term_count
                    total_matches += term_count

            # ✅ contenu section: string OU dict{text}
            if section.get("content"):
                for item in section["content"]:
                    if isinstance(item, str) and item.strip():
                        text_lower = item.lower()
                    elif isinstance(item, dict) and item.get("text"):
                        text_lower = str(item["text"]).lower()
                    else:
                        continue

                    for term in search_terms:
                        term_count = text_lower.count(term)
                        if term_count > 0:
                            score += (1 + section_importance) * term_count
                            total_matches += term_count

            # ✅ sous-sections
            if section.get('subsections'):
                for subsection in section['subsections']:
                    if not isinstance(subsection, dict):
                        continue

                    subsection_title = subsection.get('title', '')
                    subsection_title_lower = subsection_title.lower()

                    for term in search_terms:
                        term_count = subsection_title_lower.count(term)
                        if term_count > 0:
                            score += 2 * term_count
                            total_matches += term_count

                    if subsection.get("content"):
                        for item in subsection["content"]:
                            if isinstance(item, str) and item.strip():
                                text_lower = item.lower()
                            elif isinstance(item, dict) and item.get("text"):
                                text_lower = str(item["text"]).lower()
                            else:
                                continue

                            for term in search_terms:
                                term_count = text_lower.count(term)
                                if term_count > 0:
                                    score += 1 * term_count
                                    total_matches += term_count

    # Retourner la liste des matches uniques (par location et terme)
    return list(matches_dict.values())


def extract_excerpt(text, term):
    """Extrait un court extrait du texte autour du terme recherché."""
    term_lower = term.lower()
    text_lower = text.lower()
    
    # Trouver la position du terme dans le texte
    pos = text_lower.find(term_lower)
    if pos == -1:
        return text[:100] + "..."  # Retourner le début du texte si terme non trouvé
    
    # Trouver le début and la fin de la phrase contenant le terme
    sentence_start = max(0, text_lower.rfind('.', 0, pos))
    if sentence_start == 0:
        # Si pas de point trouvé, essayer d'autres délimiteurs
        sentence_start = max(0, text_lower.rfind('!', 0, pos))
        sentence_start = max(0, text_lower.rfind('?', 0, pos))
    
    sentence_end = text_lower.find('.', pos)
    if sentence_end == -1:
        # Si pas de point trouvé, chercher d'autres délimiteurs ou prendre la fin du texte
        sentence_end = text_lower.find('!', pos)
        if sentence_end == -1:
            sentence_end = text_lower.find('?', pos)
            if sentence_end == -1:
                sentence_end = len(text)
    else:
        sentence_end += 1  # Inclure le point final
    
    # Si la phrase est trop longue, créer un extrait plus court autour du terme
    if sentence_end - sentence_start > 150:
        # Calculer les positions de début and de fin pour l'extrait
        start_pos = max(0, pos - 60)
        end_pos = min(len(text), pos + len(term) + 60)
    else:
        start_pos = sentence_start
        end_pos = sentence_end
    
    # Créer l'extrait
    excerpt = ""
    if start_pos > 0:
        excerpt += "..."
    excerpt += text[start_pos:end_pos]
    if end_pos < len(text):
        excerpt += "..."
    
    return excerpt

def _safe_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def _format_date_fr(dt: Any) -> str:
    """
    Retourne une date au format dd/mm/YYYY, ou 'Non disponible' si inconnue.
    Accepte datetime / str / autres.
    """
    if dt is None:
        return "Non disponible"
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y")
    # si c'est déjà une string ISO ou autre, on la laisse (mais propre)
    return _safe_str(dt) or "Non disponible"


# ========== FONCTIONS V3 ==========

def _extract_title_v3(market_doc: Dict[str, Any]) -> str:
    """Extrait le titre depuis un document medicine_market (V3)"""
    # Priorité au brand_title
    if _safe_str(market_doc.get("brand_title")):
        return market_doc["brand_title"]
    
    # Sinon utiliser medicine_id comme fallback
    if _safe_str(market_doc.get("medicine_id")):
        return market_doc["medicine_id"]
    
    return f"Médicament {market_doc.get('_id')}"


def _extract_update_date_v3(market_doc: Dict[str, Any]) -> str:
    """Extrait la date de mise à jour depuis un document medicine_market (V3)"""
    # Chercher updated_at au niveau du document
    updated_at = market_doc.get("updated_at")
    if updated_at:
        return _format_date_fr(datetime.fromtimestamp(updated_at))
    
    # Sinon chercher dans rcp.metadata.update_date
    rcp = market_doc.get("rcp") or {}
    metadata = rcp.get("metadata") or {}
    update_date = metadata.get("update_date")
    if update_date:
        return _safe_str(update_date) or "Non disponible"
    
    return "Non disponible"


def _extract_source_url_v3(market_doc: Dict[str, Any]) -> Optional[str]:
    """Extrait l'URL source depuis un document medicine_market (V3)"""
    # Chercher dans source_urls (liste)
    source_urls = market_doc.get("source_urls") or []
    if source_urls and len(source_urls) > 0:
        return source_urls[0]
    
    # Chercher dans rcp.metadata.url
    rcp = market_doc.get("rcp") or {}
    metadata = rcp.get("metadata") or {}
    url = metadata.get("url")
    if url:
        return url
    
    return None


def _extract_medicine_details_v3(market_doc: Dict[str, Any], medicine_doc: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Extrait les détails du médicament depuis medicine_market et medicines_v3 (V3)
    Retourne: {forme, dosages, substances_actives, laboratoire}
    """
    # Données depuis medicine_market
    forme = market_doc.get("form") or ""
    strength = market_doc.get("strength") or ""
    laboratory = market_doc.get("laboratory") or ""
    
    # Dosages: peut être une string ou dans rcp.metadata
    dosages = []
    if strength:
        dosages.append(strength)
    
    rcp = market_doc.get("rcp") or {}
    metadata = rcp.get("metadata") or {}
    rcp_dosages = metadata.get("medicine_details", {}).get("dosages") or []
    if rcp_dosages:
        dosages.extend(rcp_dosages)
    
    # Dédupliquer
    dosages = list(set(dosages)) if dosages else []
    
    # Substances actives: depuis medicine_doc.inns ou rcp.metadata
    substances_actives = []
    if medicine_doc:
        inns = medicine_doc.get("inns") or []
        substances_actives.extend(inns)
    
    rcp_substances = metadata.get("medicine_details", {}).get("substances_actives") or []
    if rcp_substances:
        substances_actives.extend(rcp_substances)
    
    # Dédupliquer
    substances_actives = list(set(substances_actives)) if substances_actives else []
    
    return {
        "forme": forme,
        "dosages": dosages,
        "substances_actives": substances_actives,
        "laboratoire": laboratory,
    }


def _convert_v3_rcp_sections_to_legacy(rcp_sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convertit les sections RCP v3 vers le format legacy attendu par medicine_details.html
    Compatible avec la structure actuelle dans rcp.sections
    """
    def convert_subsections(subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for sub in subs or []:
            if not isinstance(sub, dict):
                continue

            sub_title = _safe_str(sub.get("title")) or ""
            sub_content = []
            for c in sub.get("content", []) or []:
                if isinstance(c, dict) and _safe_str(c.get("text")):
                    sub_content.append({
                        "text": c["text"],
                        "formatting": c.get("formatting") or {}
                    })
                elif isinstance(c, str) and _safe_str(c):
                    sub_content.append({
                        "text": c,
                        "formatting": {}
                    })

            out.append({
                "title": sub_title,
                "content": sub_content,
                "subsections": convert_subsections(sub.get("subsections", []) or [])
            })
        return out

    legacy_sections = []
    for sec in rcp_sections or []:
        if not isinstance(sec, dict):
            continue

        title = _safe_str(sec.get("title")) or ""
        content = []

        # Extraire le contenu
        for item in sec.get("content", []) or []:
            if isinstance(item, dict) and _safe_str(item.get("text")):
                content.append({
                    "text": item["text"],
                    "formatting": item.get("formatting") or {}
                })
            elif isinstance(item, str) and _safe_str(item):
                content.append({
                    "text": item,
                    "formatting": {}
                })

        subsections = convert_subsections(sec.get("subsections", []) or [])

        legacy_sections.append({
            "title": title,
            "content": content,
            "subsections": subsections,
        })

    return legacy_sections


def _extract_theriaque_data(market_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait les données Thériaque depuis medicine_market"""
    theriaque = market_doc.get("theriaque") or {}
    migrations = theriaque.get("migrations", {}).get("v2", [])
    
    if not migrations:
        return None
    
    data = migrations[0]  # Premier élément de migration
    
    return {
        "meta": data.get("meta") or {},
        "interactions": data.get("interactions") or {},
        "c_indic": data.get("c_indic") or {},  # Contre-indications
        "indic": data.get("indic") or {},  # Indications
    }


def _extract_pubchem_data(substance_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait les données PubChem depuis substances_v3"""
    if not substance_doc:
        return None
    
    pubchem = substance_doc.get("sources", {}).get("pubchem") or {}
    if not pubchem:
        return None
    
    summary = pubchem.get("summary") or {}
    return {
        "cid": pubchem.get("cid"),
        "molecular_formula": summary.get("molecular_formula"),
        "molecular_weight": summary.get("molecular_weight"),
        "canonical_smiles": summary.get("canonical_smiles"),
        "isomeric_smiles": summary.get("isomeric_smiles"),
        "inchi": summary.get("inchi"),
        "inchi_key": summary.get("inchi_key"),
        "synonyms_top": pubchem.get("synonyms_top", [])[:10],  # Limiter à 10
        "brand_like_names": pubchem.get("brand_like_names", [])[:5],
    }


def _extract_drugbank_data(substance_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait les données DrugBank depuis substances_v3"""
    if not substance_doc:
        return None
    
    drugbank = substance_doc.get("sources", {}).get("drugbank") or {}
    if not drugbank:
        return None
    
    return {
        "drugbank_id": drugbank.get("drugbank_id"),
        "label": drugbank.get("label"),
        "cas": drugbank.get("cas"),
        "unii": drugbank.get("unii"),
        "atc_codes": drugbank.get("atc_codes", []),
        "synonyms": drugbank.get("synonyms", [])[:10],
    }


def _get_substance_data(medicine_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Récupère les données de toutes les substances associées au médicament"""
    if not medicine_doc:
        return []
    
    substance_ref_ids = medicine_doc.get("substance_ref_ids", [])
    substances_data = []
    
    for sub_ref in substance_ref_ids:
        try:
            sub_doc = substances_v3.find_one({"_id": sub_ref})
            if sub_doc:
                substance_info = {
                    "label": sub_doc.get("label"),
                    "label_normalized": sub_doc.get("label_normalized"),
                    "pubchem": _extract_pubchem_data(sub_doc),
                    "drugbank": _extract_drugbank_data(sub_doc),
                }
                substances_data.append(substance_info)
        except Exception as e:
            print(f"Erreur lors de la récupération de substance_ref: {e}")
            continue
    
    return substances_data


def to_medicine_view_v3(market_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convertit un document medicine_market (V3) vers le format attendu par medicine_details.html
    Enrichit avec les données de medicines_v3, Thériaque, PubChem et DrugBank
    """
    view = dict(market_doc)
    
    # Récupérer le document medicine_v3 associé si disponible
    medicine_doc = None
    medicine_ref = market_doc.get("medicine_ref")
    if medicine_ref:
        try:
            medicine_doc = medicines_v3.find_one({"_id": medicine_ref})
        except Exception as e:
            print(f"Erreur lors de la récupération de medicine_ref: {e}")
    
    # Extraire les informations principales
    view["title"] = _extract_title_v3(market_doc)
    view["update_date"] = _extract_update_date_v3(market_doc)
    view["url"] = _extract_source_url_v3(market_doc)
    view["medicine_details"] = _extract_medicine_details_v3(market_doc, medicine_doc)
    
    # Extraire les sections RCP
    rcp = market_doc.get("rcp") or {}
    rcp_sections = rcp.get("sections") or []
    view["sections"] = _convert_v3_rcp_sections_to_legacy(rcp_sections)
    
    # Ajouter les données enrichies de medicine_v3
    if medicine_doc:
        view["medicine_v3"] = {
            "inns": medicine_doc.get("inns") or [],
            "countries": medicine_doc.get("countries") or [],
            "substance_labels": medicine_doc.get("substance_labels") or [],
        }
    
    # Extraire les données Thériaque
    view["theriaque_data"] = _extract_theriaque_data(market_doc)
    
    # Extraire les données des substances (PubChem + DrugBank)
    view["substances_data"] = _get_substance_data(medicine_doc)
    
    return view


def _extract_title(doc: Dict[str, Any]) -> str:
    # v2
    drug = doc.get("drug") or {}
    if _safe_str(drug.get("full_title")):
        return drug["full_title"]
    if _safe_str(drug.get("name")):
        return drug["name"]

    # v1
    if _safe_str(doc.get("title")):
        return doc["title"]

    return f"Médicament {doc.get('_id')}"


def _extract_source_url(doc: Dict[str, Any]) -> Optional[str]:
    # v2 : la vraie url est souvent dans source.url (car doc.url peut être null)
    if _safe_str(doc.get("url")):
        return doc["url"]
    source = doc.get("source") or {}
    return _safe_str(source.get("url"))


def _extract_update_date(doc: Dict[str, Any]) -> str:
    # v2 : document.updated_at
    d = (doc.get("document") or {}).get("updated_at")
    if d:
        return _format_date_fr(d)

    # v1 : update_date
    return _format_date_fr(doc.get("update_date"))


def _extract_medicine_details(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retourne un dict avec: forme, dosages(list), substances_actives(list), laboratoire
    Compatible v1/v2.
    """
    # v1 direct si présent
    md = doc.get("medicine_details")
    if isinstance(md, dict) and md:
        # normaliser les listes si jamais string
        dos = md.get("dosages") or []
        subs = md.get("substances_actives") or []
        if isinstance(dos, str):
            dos = [dos]
        if isinstance(subs, str):
            subs = [subs]
        return {
            "forme": md.get("forme"),
            "dosages": dos,
            "substances_actives": subs,
            "laboratoire": md.get("laboratoire"),
        }

    # v2 depuis drug
    drug = doc.get("drug") or {}
    dosages = drug.get("strengths") or []
    subs = drug.get("active_substances") or []
    if isinstance(dosages, str):
        dosages = [dosages]
    if isinstance(subs, str):
        subs = [subs]

    return {
        "forme": drug.get("form"),
        "dosages": dosages,
        "substances_actives": subs,
        "laboratoire": drug.get("laboratory"),
    }


def _as_legacy_content_item(text: str, formatting: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Ton template attend content_item['text'] et optionnellement content_item['formatting'].
    """
    item = {"text": text}
    if formatting:
        item["formatting"] = formatting
    return item


def _convert_v2_rcp_sections_to_legacy(rcp_sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convertit v2 rcp.sections (blocks + subsections) vers le format legacy attendu par medicine_details.html:
    sections: [{title, content:[{text, formatting?...}], subsections:[{title, content:[{text, formatting?...}], subsections:...}]}]
    """
    def convert_subsections(subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for sub in subs or []:
            if not isinstance(sub, dict):
                continue

            sub_title = _safe_str(sub.get("title")) or ""
            sub_content = []
            for c in sub.get("content", []) or []:
                if isinstance(c, dict) and _safe_str(c.get("text")):
                    # v2: formatting peut être sous "formatting"
                    sub_content.append(_as_legacy_content_item(c["text"], c.get("formatting")))
                elif isinstance(c, str) and _safe_str(c):
                    sub_content.append(_as_legacy_content_item(c))

            out.append({
                "title": sub_title,
                "content": sub_content,
                "subsections": convert_subsections(sub.get("subsections", []) or [])
            })
        return out

    legacy_sections = []
    for sec in rcp_sections or []:
        if not isinstance(sec, dict):
            continue

        title = _safe_str(sec.get("title")) or ""
        content = []

        # v2: blocks = [{text, style{...}}]
        for b in sec.get("blocks", []) or []:
            if isinstance(b, dict) and _safe_str(b.get("text")):
                # On mappe "style" -> "formatting" pour coller au template
                style = b.get("style") or {}
                formatting = {
                    "bold": bool(style.get("bold", False)),
                    "italic": bool(style.get("italic", False)),
                    "underline": bool(style.get("underline", False)),
                    "alignment": style.get("align", "left"),
                    "list_type": style.get("list"),
                }
                content.append(_as_legacy_content_item(b["text"], formatting))
            elif isinstance(b, str) and _safe_str(b):
                content.append(_as_legacy_content_item(b))

        subsections = convert_subsections(sec.get("subsections", []) or [])

        legacy_sections.append({
            "title": title,
            "content": content,
            "subsections": subsections,
        })

    return legacy_sections


def to_medicine_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Modèle canonique (stable) pour la page medicine_details.html.
    -> garantit title/update_date/url/medicine_details/sections quelque soit schema v1/v2.
    """
    view = dict(doc)  # copie shallow (suffisant pour template)

    view["title"] = _extract_title(doc)
    view["update_date"] = _extract_update_date(doc)
    view["url"] = _extract_source_url(doc)

    view["medicine_details"] = _extract_medicine_details(doc)

    # sections
    if doc.get("sections"):
        # v1 déjà au bon format
        view["sections"] = doc["sections"]
    else:
        rcp_sections = (doc.get("rcp") or {}).get("sections") or []
        view["sections"] = _convert_v2_rcp_sections_to_legacy(rcp_sections)

    return view


def get_pharmgkb_data(medicine_name, substances_actives=None):
    """
    Récupère les données pharmacogénomiques depuis PharmGKB
    
    Args:
        medicine_name: Nom du médicament
        substances_actives: Liste des substances actives du médicament
        
    Returns:
        dict: {
            'drug_info': {...},  # Info du médicament PharmGKB
            'relationships': [...],  # Relations pharmacogénomiques
            'genes': [...],  # Liste des gènes associés
        }
    """
    try:
        pharmgkb_data = {
            'drug_info': None,
            'relationships': [],
            'genes': []
        }
        
        # Fonction pour nettoyer et extraire le nom principal
        def clean_name(name):
            """Nettoie un nom de médicament pour la recherche"""
            if not name:
                return ""
            # Retirer les dosages, formes, etc.
            name = name.lower().strip()
            # Retirer les chiffres et mg, g, etc.
            import re
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
        
        # Collecter tous les noms à rechercher
        search_names = set()
        
        # Ajouter le nom du médicament (nettoyé et original)
        cleaned_medicine_name = clean_name(medicine_name)
        if cleaned_medicine_name:
            search_names.add(cleaned_medicine_name)
            # Ajouter aussi juste le premier mot (nom commercial souvent)
            first_word = cleaned_medicine_name.split()[0] if cleaned_medicine_name.split() else ""
            if first_word and len(first_word) > 3:
                search_names.add(first_word)
        
        # Ajouter les substances actives (PRIORITÉ)
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
                    # Nettoyer aussi la substance
                    cleaned_sub = clean_name(sub_name)
                    if cleaned_sub and cleaned_sub != sub_name:
                        search_names.add(cleaned_sub)
        
        print(f"🔍 Recherche PharmGKB pour: {list(search_names)}")
        
        # Chercher le médicament dans pharmgkb_drugs
        # Prioriser les substances actives si présentes
        search_order = sorted(search_names, key=lambda x: (
            # Les substances actives en premier (généralement sans espaces/tirets)
            ' ' in x or '-' in x,
            # Les plus longs noms ensuite
            -len(x)
        ))
        
        for name in search_order:
            if not name or len(name) < 3:
                continue
                
            # Essayer correspondance exacte
            drug = db.pharmgkb_drugs.find_one({'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}})
            
            if not drug:
                # Essayer correspondance partielle sur le nom
                drug = db.pharmgkb_drugs.find_one({'name': {'$regex': re.escape(name), '$options': 'i'}})
            
            if not drug:
                # Chercher dans les synonymes
                drug = db.pharmgkb_drugs.find_one({'synonyms': {'$regex': re.escape(name), '$options': 'i'}})
            
            if not drug:
                # Essayer aussi via drug_name dans relationships directement
                rel = db.pharmgkb_relationships.find_one({'drug_name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}})
                if rel:
                    # Trouver le drug correspondant
                    drug = db.pharmgkb_drugs.find_one({'pharmgkb_id': rel.get('pharmgkb_drug_id')})
            
            if drug:
                print(f"✅ Trouvé dans PharmGKB: {drug.get('name')} (ID: {drug.get('pharmgkb_id')})")
                pharmgkb_data['drug_info'] = drug
                
                # Récupérer les relations pharmacogénomiques
                relationships = list(db.pharmgkb_relationships.find({
                    'pharmgkb_drug_id': drug.get('pharmgkb_id')
                }))
                
                if relationships:
                    pharmgkb_data['relationships'] = relationships
                    
                    # Extraire les gènes uniques et les organiser
                    genes_dict = {}
                    for rel in relationships:
                        gene = rel.get('gene_symbol')
                        if gene:
                            if gene not in genes_dict:
                                genes_dict[gene] = {
                                    'symbol': gene,
                                    'associations': [],
                                    'pk_count': 0,
                                    'pd_count': 0
                                }
                            
                            genes_dict[gene]['associations'].append({
                                'association': rel.get('association'),
                                'evidence': rel.get('evidence'),
                                'pk': rel.get('pk'),
                                'pd': rel.get('pd'),
                                'pmids': rel.get('pmids', [])
                            })
                            
                            if rel.get('pk'):
                                genes_dict[gene]['pk_count'] += 1
                            if rel.get('pd'):
                                genes_dict[gene]['pd_count'] += 1
                    
                    pharmgkb_data['genes'] = list(genes_dict.values())
                    print(f"✅ {len(pharmgkb_data['genes'])} gènes trouvés")
                
                break  # On a trouvé, pas besoin de chercher plus
        
        if not pharmgkb_data['drug_info']:
            print(f"ℹ️  Aucune donnée PharmGKB trouvée pour: {medicine_name}")
        
        return pharmgkb_data
        
    except Exception as e:
        print(f"⚠️  Erreur lors de la récupération des données PharmGKB: {e}")
        import traceback
        traceback.print_exc()
        return {'drug_info': None, 'relationships': [], 'genes': []}


def get_drugbank_chunks(substances_actives):
    """
    Récupère les chunks DrugBank pour les substances actives
    
    Args:
        substances_actives: Liste des substances actives du médicament
        
    Returns:
        dict: {
            'interactions': [...],  # Interactions médicamenteuses (pour pharmaciens!)
            'targets': [...],  # Cibles thérapeutiques (mécanisme d'action)
            'enzymes': [...],  # Métabolisme enzymatique (CYP450 crucial!)
            'pathways': [...],  # Voies métaboliques
            'transporters': [...],  # Transporteurs membranaires
            'carriers': [...],  # Protéines de transport
        }
    """
    try:
        drugbank_data = {
            'interactions': [],
            'targets': [],
            'enzymes': [],
            'pathways': [],
            'transporters': [],
            'carriers': []
        }
        
        if not substances_actives:
            return drugbank_data
        
        # Récupérer les drugbank_ids des substances
        drugbank_ids = set()
        
        for substance_name in substances_actives:
            # Chercher la substance dans substances_v3
            substance = substances_v3.find_one({
                '$or': [
                    {'label_normalized': substance_name.upper()},
                    {'label': {'$regex': f'^{re.escape(substance_name)}', '$options': 'i'}}
                ]
            })
            
            if substance:
                drugbank_id = substance.get('sources', {}).get('drugbank', {}).get('drugbank_id')
                if drugbank_id:
                    drugbank_ids.add(drugbank_id)
                    print(f"🔍 DrugBank ID trouvé pour {substance_name}: {drugbank_id}")
        
        if not drugbank_ids:
            print(f"ℹ️  Aucun DrugBank ID trouvé pour les substances")
            return drugbank_data
        
        # Récupérer les chunks pour chaque drugbank_id
        for drugbank_id in drugbank_ids:
            # Interactions médicamenteuses (CRUCIAL pour pharmaciens!)
            interactions_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'drug-interactions'
            })
            if interactions_chunk and interactions_chunk.get('data'):
                data = interactions_chunk['data']
                if isinstance(data, list):
                    # Limiter à 20 interactions les plus importantes
                    drugbank_data['interactions'].extend(data[:20])
            
            # Cibles thérapeutiques (mécanisme d'action)
            targets_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'targets'
            })
            if targets_chunk and targets_chunk.get('data'):
                data = targets_chunk['data']
                if isinstance(data, list):
                    drugbank_data['targets'].extend(data)
            
            # Enzymes (métabolisme CYP450 - CRUCIAL!)
            enzymes_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'enzymes'
            })
            if enzymes_chunk and enzymes_chunk.get('data'):
                data = enzymes_chunk['data']
                if isinstance(data, list):
                    drugbank_data['enzymes'].extend(data)
            
            # Voies métaboliques
            pathways_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'pathways'
            })
            if pathways_chunk and pathways_chunk.get('data'):
                data = pathways_chunk['data']
                if isinstance(data, list):
                    drugbank_data['pathways'].extend(data)
            
            # Transporteurs
            transporters_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'transporters'
            })
            if transporters_chunk and transporters_chunk.get('data'):
                data = transporters_chunk['data']
                if isinstance(data, list):
                    drugbank_data['transporters'].extend(data)
            
            # Carriers
            carriers_chunk = db.drugbank_raw_chunks.find_one({
                'drugbank_id': drugbank_id,
                'kind': 'carriers'
            })
            if carriers_chunk and carriers_chunk.get('data'):
                data = carriers_chunk['data']
                if isinstance(data, list):
                    drugbank_data['carriers'].extend(data)
        
        print(f"✅ DrugBank chunks récupérés: {len(drugbank_data['interactions'])} interactions, {len(drugbank_data['targets'])} cibles, {len(drugbank_data['enzymes'])} enzymes")
        
        return drugbank_data
        
    except Exception as e:
        print(f"⚠️  Erreur lors de la récupération des chunks DrugBank: {e}")
        import traceback
        traceback.print_exc()
        return {
            'interactions': [],
            'targets': [],
            'enzymes': [],
            'pathways': [],
            'transporters': [],
            'carriers': []
        }


@app.route('/medicine/<id>')
def medicine_details(id):
    """Route pour les détails d'un médicament spécifique (compatible schema v1/v2)"""
    try:
        medicine = collection.find_one({'_id': ObjectId(id)})
        if not medicine:
            abort(404)

        # ✅ Convertit le document brut (v1 ou v2) vers un modèle stable attendu par le template
        medicine = to_medicine_view(medicine)

        # ✅ name utilisé ailleurs dans ton front (garde compat)
        # extract_medicine_name() doit normalement retourner le bon titre (v1/v2)
        medicine['name'] = extract_medicine_name(medicine)

        # ✅ Summary IA (cache) : ne pas bloquer si absent
        existing_summary = None
        if db is not None:
            try:
                stored_medicine = db.medicines.find_one(
                    {"_id": ObjectId(id)},
                    {"ai_summary": 1}
                )
                if stored_medicine and 'ai_summary' in stored_medicine:
                    existing_summary = stored_medicine['ai_summary']
            except Exception as e:
                print(f"Error checking for cached summary: {e}")
        
        # Si pas de résumé en cache, lancer la génération en arrière-plan
        if not existing_summary:
            try:
                from threading import Thread
                def generate_summary_background():
                    """Génère le résumé en arrière-plan"""
                    try:
                        print(f"🤖 Génération du résumé IA pour {medicine.get('name', id)}...")
                        summary = get_or_generate_summary(medicine, db=db)
                        print(f"✅ Résumé généré et sauvegardé pour {medicine.get('name', id)}")
                    except Exception as e:
                        print(f"❌ Erreur lors de la génération du résumé: {e}")
                
                # Lancer dans un thread séparé pour ne pas bloquer la page
                thread = Thread(target=generate_summary_background)
                thread.daemon = True
                thread.start()
                print(f"🚀 Génération du résumé lancée en arrière-plan")
            except Exception as e:
                print(f"Erreur lors du lancement de la génération en arrière-plan: {e}")

        medicine['ai_summary'] = existing_summary

        # ✅ Favoris + commentaires
        is_favorite = False
        comments = []
        user_role = None

        if 'user_id' in request.cookies:
            from models import Interaction, Comment
            user_id = request.cookies.get('user_id')
            is_favorite = Interaction.is_favorite(user_id, str(medicine['_id']))

            user_role = request.cookies.get('role')
            if user_role:
                try:
                    user_role = int(user_role)
                except Exception:
                    user_role = None

            comments = Comment.get_for_medicine(str(medicine['_id']), user_role)
        else:
            from models import Comment
            comments = Comment.get_for_medicine(str(medicine['_id']))

        # ✅ Ajouter les infos utilisateur à chaque commentaire
        for comment in comments:
            try:
                comment_user = User.get_by_id(comment['user_id'])
                if comment_user:
                    comment['user'] = {
                        'first_name': comment_user.get('first_name', 'Utilisateur'),
                        'last_name': comment_user.get('last_name', '')
                    }
                else:
                    comment['user'] = {'first_name': 'Utilisateur', 'last_name': ''}
            except Exception as e:
                print(f"Erreur lors de la récupération des données utilisateur: {e}")
                comment['user'] = {'first_name': 'Utilisateur', 'last_name': ''}

        # ✅ Récupérer les données pharmacogénomiques PharmGKB
        pharmgkb_data = None
        try:
            # Extraire le nom du médicament et les substances actives
            medicine_name = medicine.get('name', '')
            substances_actives = []
            
            # Essayer plusieurs sources pour les substances actives
            # 1. Depuis medicine_details (format v1)
            if medicine.get('medicine_details'):
                subs = medicine['medicine_details'].get('substances_actives', [])
                if subs:
                    substances_actives.extend(subs if isinstance(subs, list) else [subs])
            
            # 2. Depuis drug.active_substances (format v2)
            if medicine.get('drug', {}).get('active_substances'):
                subs = medicine['drug']['active_substances']
                substances_actives.extend(subs if isinstance(subs, list) else [subs])
            
            # 3. Depuis le document brut original (avant transformation)
            raw_doc = collection.find_one({'_id': ObjectId(id)})
            if raw_doc:
                if raw_doc.get('medicine_details', {}).get('substances_actives'):
                    subs = raw_doc['medicine_details']['substances_actives']
                    substances_actives.extend(subs if isinstance(subs, list) else [subs])
                if raw_doc.get('drug', {}).get('active_substances'):
                    subs = raw_doc['drug']['active_substances']
                    substances_actives.extend(subs if isinstance(subs, list) else [subs])
            
            # Dédupliquer
            substances_actives = list(set([s if isinstance(s, str) else s.get('nom', '') if isinstance(s, dict) else str(s) for s in substances_actives if s]))
            
            print(f"🔍 PharmGKB - Médicament: {medicine_name}")
            print(f"🔍 PharmGKB - Substances actives trouvées: {substances_actives}")
            
            # Récupérer les données PharmGKB
            if substances_actives or medicine_name:
                pharmgkb_data = get_pharmgkb_data(medicine_name, substances_actives)
                
                # Afficher un message de débogage
                if pharmgkb_data and pharmgkb_data.get('drug_info'):
                    print(f"✅ Données PharmGKB trouvées pour {medicine_name}: {len(pharmgkb_data.get('genes', []))} gènes")
                else:
                    print(f"ℹ️  Aucune donnée PharmGKB trouvée pour {medicine_name}")
            else:
                print(f"⚠️  Aucune substance active trouvée pour {medicine_name}")
        except Exception as e:
            print(f"⚠️  Erreur lors de la récupération des données PharmGKB: {e}")
            import traceback
            traceback.print_exc()
            pharmgkb_data = None

        # ✅ Normaliser content/subcontent pour l'affichage (crée html_content si absent)
        # Ici on suppose que medicine['sections'] est au format legacy:
        # sections: [{title, content:[{text, formatting?}], subsections:[{title, content:[...]}]}]
        if medicine.get('sections'):
            for section in medicine['sections']:
                if not isinstance(section, dict):
                    continue

                # Section content
                if section.get('content'):
                    new_content = []
                    for item in section['content']:
                        # item peut être str ou dict{text,...}
                        if isinstance(item, str) and item.strip():
                            text = item
                            html_text = text.replace('\n', '<br>')
                            new_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                        elif isinstance(item, dict) and item.get('text'):
                            if 'html_content' not in item:
                                text = str(item['text'])
                                html_text = text.replace('\n', '<br>')
                                item['html_content'] = f"<p>{html_text}</p>"
                            new_content.append(item)
                    section['content'] = new_content

                # Subsections content (1 niveau)
                if section.get('subsections'):
                    for subsection in section['subsections']:
                        if not isinstance(subsection, dict):
                            continue
                        if subsection.get('content'):
                            new_sub_content = []
                            for item in subsection['content']:
                                if isinstance(item, str) and item.strip():
                                    text = item
                                    html_text = text.replace('\n', '<br>')
                                    new_sub_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                                elif isinstance(item, dict) and item.get('text'):
                                    if 'html_content' not in item:
                                        text = str(item['text'])
                                        html_text = text.replace('\n', '<br>')
                                        item['html_content'] = f"<p>{html_text}</p>"
                                    new_sub_content.append(item)
                            subsection['content'] = new_sub_content

                        # (Optionnel mais solide) : si tu as des sous-sous-sections legacy, on normalise aussi
                        if subsection.get('subsections'):
                            for subsub in subsection['subsections']:
                                if not isinstance(subsub, dict):
                                    continue
                                if subsub.get('content'):
                                    new_subsub_content = []
                                    for item in subsub['content']:
                                        if isinstance(item, str) and item.strip():
                                            text = item
                                            html_text = text.replace('\n', '<br>')
                                            new_subsub_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                                        elif isinstance(item, dict) and item.get('text'):
                                            if 'html_content' not in item:
                                                text = str(item['text'])
                                                html_text = text.replace('\n', '<br>')
                                                item['html_content'] = f"<p>{html_text}</p>"
                                            new_subsub_content.append(item)
                                    subsub['content'] = new_subsub_content

        # ✅ JSON brut (pour "Afficher JSON")
        medicine_json = json.dumps(bson_to_json(medicine), indent=2, ensure_ascii=False)

        return render_template(
            'medicine_details.html',
            medicine=medicine,
            medicine_json=medicine_json,
            is_favorite=is_favorite,
            comments=comments,
            pharmgkb_data=pharmgkb_data
        )

    except Exception as e:
        print(f"Erreur dans medicine_details: {e}")
        abort(404)


@app.route('/pubchem-image/<int:cid>')
def pubchem_image(cid):
    """Servir les images 2D PubChem depuis data/pubchem_images/"""
    from flask import send_from_directory
    import os
    
    try:
        # Le dossier data est monté dans /data dans le container Docker
        # En local, il est dans ../data depuis frontend_backend
        if os.path.exists('/data/pubchem_images'):
            images_dir = '/data/pubchem_images'
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            images_dir = os.path.join(base_dir, 'data', 'pubchem_images')
        
        # Nom du fichier
        filename = f'cid_{cid}_2d.png'
        
        # Vérifier si le fichier existe
        filepath = os.path.join(images_dir, filename)
        if os.path.exists(filepath):
            return send_from_directory(images_dir, filename, mimetype='image/png')
        else:
            # Retourner une image placeholder ou 404
            abort(404)
    except Exception as e:
        print(f"Erreur lors du service de l'image PubChem CID {cid}: {e}")
        abort(404)


@app.route('/medicine-market/<id>')
def medicine_market_details(id):
    """Route pour les détails d'un médicament V3 depuis medicine_market"""
    try:
        # Rechercher dans medicine_market par _id (string compound key)
        market_doc = medicine_market.find_one({'_id': id})
        
        if not market_doc:
            # Fallback: chercher par market_key
            market_doc = medicine_market.find_one({'market_key': id})
        
        if not market_doc:
            # Fallback: chercher par CIS (pour compatibilité)
            market_doc = medicine_market.find_one({'cis': id})
        
        if not market_doc:
            abort(404)

        # Convertir vers le format attendu par le template
        medicine = to_medicine_view_v3(market_doc)
        
        # Nom utilisé ailleurs dans le front
        medicine['name'] = medicine['title']

        # Summary IA (cache) : ne pas bloquer si absent
        existing_summary = None
        if db is not None:
            try:
                stored_medicine = db.medicine_market.find_one(
                    {"_id": market_doc['_id']},
                    {"ai_summary": 1}
                )
                if stored_medicine and 'ai_summary' in stored_medicine:
                    existing_summary = stored_medicine['ai_summary']
            except Exception as e:
                print(f"Error checking for cached summary: {e}")
        
        # Si pas de résumé en cache, lancer la génération en arrière-plan
        if not existing_summary:
            try:
                from threading import Thread
                def generate_summary_background():
                    """Génère le résumé en arrière-plan"""
                    try:
                        print(f"🤖 Génération du résumé IA pour {medicine.get('name', market_doc['_id'])}...")
                        # Utiliser medicine_market comme collection de sauvegarde
                        summary = get_or_generate_summary(medicine, db=db)
                        # Sauvegarder dans medicine_market
                        db.medicine_market.update_one(
                            {"_id": market_doc['_id']},
                            {"$set": {"ai_summary": summary}}
                        )
                        print(f"✅ Résumé généré et sauvegardé pour {medicine.get('name', market_doc['_id'])}")
                    except Exception as e:
                        print(f"❌ Erreur lors de la génération du résumé: {e}")
                
                # Lancer dans un thread séparé pour ne pas bloquer la page
                thread = Thread(target=generate_summary_background)
                thread.daemon = True
                thread.start()
                print(f"🚀 Génération du résumé lancée en arrière-plan pour medicine-market")
            except Exception as e:
                print(f"Erreur lors du lancement de la génération en arrière-plan: {e}")

        medicine['ai_summary'] = existing_summary

        # Favoris + commentaires
        is_favorite = False
        comments = []
        user_role = None

        if 'user_id' in request.cookies:
            from models import Interaction, Comment
            user_id = request.cookies.get('user_id')
            # Utiliser le _id du medicine_market pour les favoris
            is_favorite = Interaction.is_favorite(user_id, str(market_doc['_id']))

            user_role = request.cookies.get('role')
            if user_role:
                try:
                    user_role = int(user_role)
                except Exception:
                    user_role = None

            comments = Comment.get_for_medicine(str(market_doc['_id']), user_role)
        else:
            from models import Comment
            comments = Comment.get_for_medicine(str(market_doc['_id']))

        # Ajouter les infos utilisateur à chaque commentaire
        for comment in comments:
            try:
                comment_user = User.get_by_id(comment['user_id'])
                if comment_user:
                    comment['user'] = {
                        'first_name': comment_user.get('first_name', 'Utilisateur'),
                        'last_name': comment_user.get('last_name', '')
                    }
                else:
                    comment['user'] = {'first_name': 'Utilisateur', 'last_name': ''}
            except Exception as e:
                print(f"Erreur lors de la récupération des données utilisateur: {e}")
                comment['user'] = {'first_name': 'Utilisateur', 'last_name': ''}

        # Normaliser content pour l'affichage
        if medicine.get('sections'):
            for section in medicine['sections']:
                if not isinstance(section, dict):
                    continue

                # Section content
                if section.get('content'):
                    new_content = []
                    for item in section['content']:
                        if isinstance(item, str) and item.strip():
                            text = item
                            html_text = text.replace('\n', '<br>')
                            new_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                        elif isinstance(item, dict) and item.get('text'):
                            if 'html_content' not in item:
                                text = str(item['text'])
                                html_text = text.replace('\n', '<br>')
                                item['html_content'] = f"<p>{html_text}</p>"
                            new_content.append(item)
                    section['content'] = new_content

                # Subsections content
                if section.get('subsections'):
                    for subsection in section['subsections']:
                        if not isinstance(subsection, dict):
                            continue
                        if subsection.get('content'):
                            new_sub_content = []
                            for item in subsection['content']:
                                if isinstance(item, str) and item.strip():
                                    text = item
                                    html_text = text.replace('\n', '<br>')
                                    new_sub_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                                elif isinstance(item, dict) and item.get('text'):
                                    if 'html_content' not in item:
                                        text = str(item['text'])
                                        html_text = text.replace('\n', '<br>')
                                        item['html_content'] = f"<p>{html_text}</p>"
                                    new_sub_content.append(item)
                            subsection['content'] = new_sub_content

                        # Sous-sous-sections
                        if subsection.get('subsections'):
                            for subsub in subsection['subsections']:
                                if not isinstance(subsub, dict):
                                    continue
                                if subsub.get('content'):
                                    new_subsub_content = []
                                    for item in subsub['content']:
                                        if isinstance(item, str) and item.strip():
                                            text = item
                                            html_text = text.replace('\n', '<br>')
                                            new_subsub_content.append({"text": text, "html_content": f"<p>{html_text}</p>"})
                                        elif isinstance(item, dict) and item.get('text'):
                                            if 'html_content' not in item:
                                                text = str(item['text'])
                                                html_text = text.replace('\n', '<br>')
                                                item['html_content'] = f"<p>{html_text}</p>"
                                            new_subsub_content.append(item)
                                    subsub['content'] = new_subsub_content

        # ✅ Récupérer les données pharmacogénomiques PharmGKB
        pharmgkb_data = None
        try:
            # Extraire le nom du médicament et les substances actives
            medicine_name = medicine.get('name', '') or medicine.get('title', '')
            substances_actives = []
            
            # 1. Depuis medicine_details (format V3)
            if medicine.get('medicine_details'):
                subs = medicine['medicine_details'].get('substances_actives', [])
                if subs:
                    substances_actives.extend(subs if isinstance(subs, list) else [subs])
            
            # 2. Depuis market_doc directement
            if market_doc.get('rcp', {}).get('metadata', {}).get('medicine_details', {}).get('substances_actives'):
                subs = market_doc['rcp']['metadata']['medicine_details']['substances_actives']
                substances_actives.extend(subs if isinstance(subs, list) else [subs])
            
            # 3. Depuis medicine_doc.inns (substances actives V3)
            if market_doc.get('medicine_id'):
                try:
                    # Essayer d'abord comme ObjectId (nouveau format)
                    medicine_doc = medicines_v3.find_one({'_id': ObjectId(market_doc['medicine_id'])})
                except:
                    # Sinon comme string (ancien format)
                    medicine_doc = medicines_v3.find_one({'_id': market_doc['medicine_id']})
                
                if medicine_doc:
                    inns = medicine_doc.get('inns', [])
                    if inns:
                        substances_actives.extend(inns if isinstance(inns, list) else [inns])
                    
                    # Aussi depuis substance_labels
                    substance_labels = medicine_doc.get('substance_labels', [])
                    if substance_labels:
                        substances_actives.extend(substance_labels if isinstance(substance_labels, list) else [substance_labels])
            
            # Dédupliquer et nettoyer
            substances_actives = list(set([s.strip() if isinstance(s, str) else s.get('nom', '').strip() if isinstance(s, dict) else str(s).strip() for s in substances_actives if s]))
            
            print(f"🔍 PharmGKB (market) - Médicament: {medicine_name}")
            print(f"🔍 PharmGKB (market) - Substances actives trouvées: {substances_actives}")
            
            # Récupérer les données PharmGKB
            if substances_actives or medicine_name:
                pharmgkb_data = get_pharmgkb_data(medicine_name, substances_actives)
                
                # Afficher un message de débogage
                if pharmgkb_data and pharmgkb_data.get('drug_info'):
                    print(f"✅ Données PharmGKB trouvées pour {medicine_name}: {len(pharmgkb_data.get('genes', []))} gènes")
                else:
                    print(f"ℹ️  Aucune donnée PharmGKB trouvée pour {medicine_name}")
            else:
                print(f"⚠️  Aucune substance active trouvée pour {medicine_name}")
        except Exception as e:
            print(f"⚠️  Erreur lors de la récupération des données PharmGKB: {e}")
            import traceback
            traceback.print_exc()
            pharmgkb_data = None

        # ✅ Récupérer les images 2D PubChem pour les substances actives
        substance_images = []
        try:
            # Collecter les noms de substances actives depuis différentes sources
            substance_names = set()
            
            def normalize_substance_name(name):
                """Normalise le nom de substance en retirant les préfixes chimiques et normalisant"""
                import re
                if not name:
                    return None
                # Retirer les préfixes chimiques courants (17 β, 17 alpha, L-, D-, etc.)
                # et normaliser en majuscules
                cleaned = re.sub(r'^(17\s*[βα]?|L-|D-|DL-)\s*', '', name.strip(), flags=re.IGNORECASE)
                # Retirer les astérisques et autres caractères spéciaux
                cleaned = re.sub(r'[*]', '', cleaned)
                # Retirer les espaces multiples
                cleaned = re.sub(r'\s+', ' ', cleaned)
                return cleaned.strip().upper()
            
            # 1. Depuis medicine_details (format V3)
            if medicine.get('medicine_details'):
                subs = medicine['medicine_details'].get('substances_actives', [])
                if subs:
                    for sub in (subs if isinstance(subs, list) else [subs]):
                        if isinstance(sub, str):
                            normalized = normalize_substance_name(sub)
                            if normalized:
                                substance_names.add(normalized)
                        elif isinstance(sub, dict) and sub.get('nom'):
                            normalized = normalize_substance_name(sub['nom'])
                            if normalized:
                                substance_names.add(normalized)
            
            # 2. Depuis market_doc.rcp.metadata
            if market_doc.get('rcp', {}).get('metadata', {}).get('medicine_details', {}).get('substances_actives'):
                subs = market_doc['rcp']['metadata']['medicine_details']['substances_actives']
                for sub in (subs if isinstance(subs, list) else [subs]):
                    if isinstance(sub, str):
                        normalized = normalize_substance_name(sub)
                        if normalized:
                            substance_names.add(normalized)
                    elif isinstance(sub, dict) and sub.get('nom'):
                        normalized = normalize_substance_name(sub['nom'])
                        if normalized:
                            substance_names.add(normalized)
            
            # 3. Depuis medicine_doc.inns (substances actives V3)
            if market_doc.get('medicine_id'):
                try:
                    medicine_doc = medicines_v3.find_one({'_id': ObjectId(market_doc['medicine_id'])})
                except:
                    medicine_doc = medicines_v3.find_one({'_id': market_doc['medicine_id']})
                
                if medicine_doc:
                    inns = medicine_doc.get('inns', [])
                    for inn in (inns if isinstance(inns, list) else [inns]):
                        if isinstance(inn, str):
                            normalized = normalize_substance_name(inn)
                            if normalized:
                                substance_names.add(normalized)
            
            print(f"🔍 Substances normalisées: {substance_names}")
            
            # Maintenant chercher les substances dans substances_v3 par leur label_normalized
            if substance_names:
                import os
                # Le dossier data est monté dans /data dans le container Docker
                # En local, il est dans ../data depuis frontend_backend
                if os.path.exists('/data/pubchem_images'):
                    pubchem_images_dir = '/data/pubchem_images'
                else:
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    pubchem_images_dir = os.path.join(base_dir, 'data', 'pubchem_images')
                
                for substance_name in substance_names:
                    # Chercher la substance par label_normalized (recherche exacte)
                    substance = substances_v3.find_one({
                        'label_normalized': substance_name
                    })
                    
                    # Si pas trouvé, essayer une recherche plus souple (regex)
                    if not substance:
                        substance = substances_v3.find_one({
                            'label_normalized': {'$regex': f'^{re.escape(substance_name)}', '$options': 'i'}
                        })
                    
                    if substance:
                        cid = substance.get('sources', {}).get('pubchem', {}).get('cid')
                        label = substance.get('label', substance_name.title())
                        
                        if cid:
                            # Vérifier si l'image existe
                            image_path = os.path.join(pubchem_images_dir, f'cid_{cid}_2d.png')
                            
                            if os.path.exists(image_path):
                                substance_images.append({
                                    'cid': cid,
                                    'label': label,
                                    'url': url_for('pubchem_image', cid=cid)
                                })
                                print(f"✅ Image 2D trouvée pour {label} (CID: {cid})")
                            else:
                                print(f"❌ Image manquante pour {label} (CID: {cid})")
                        else:
                            print(f"⚠️ Pas de CID pour {label}")
                    else:
                        print(f"❌ Substance non trouvée: {substance_name}")
                
                print(f"📊 Total images 2D trouvées: {len(substance_images)} sur {len(substance_names)} substances")
        except Exception as e:
            print(f"Erreur lors de la récupération des images PubChem: {e}")
            import traceback
            traceback.print_exc()

        # ✅ Récupérer les chunks DrugBank (interactions, métabolisme, etc.)
        drugbank_chunks = None
        try:
            # Collecter les noms de substances actives
            substances_list = []
            if substance_names:
                substances_list = list(substance_names)
            
            if substances_list:
                drugbank_chunks = get_drugbank_chunks(substances_list)
                
                if drugbank_chunks and any([
                    drugbank_chunks.get('interactions'),
                    drugbank_chunks.get('targets'),
                    drugbank_chunks.get('enzymes'),
                    drugbank_chunks.get('pathways')
                ]):
                    print(f"✅ Chunks DrugBank récupérés pour {medicine.get('name', market_doc['_id'])}")
                else:
                    print(f"ℹ️  Aucun chunk DrugBank trouvé pour {medicine.get('name', market_doc['_id'])}")
            else:
                print(f"⚠️  Aucune substance active pour récupérer DrugBank chunks")
        except Exception as e:
            print(f"⚠️  Erreur lors de la récupération des chunks DrugBank: {e}")
            import traceback
            traceback.print_exc()
            drugbank_chunks = None

        # JSON brut (pour "Afficher JSON")
        medicine_json = json.dumps(bson_to_json(medicine), indent=2, ensure_ascii=False)

        # ✅ Classification Grossesse / Allaitement depuis RCP section 4.6
        pregnancy_data = None
        try:
            rcp = market_doc.get("rcp") or {}
            if rcp and isinstance(rcp, dict) and rcp.get("sections"):
                pregnancy_data = classify_pregnancy_breastfeeding(rcp)
        except Exception as e:
            print(f"⚠️  Erreur classification grossesse: {e}")

        return render_template(
            'medicine_details.html',
            medicine=medicine,
            medicine_json=medicine_json,
            is_favorite=is_favorite,
            comments=comments,
            pharmgkb_data=pharmgkb_data,
            substance_images=substance_images,
            drugbank_chunks=drugbank_chunks,
            pregnancy_data=pregnancy_data
        )

    except Exception as e:
        print(f"Erreur dans medicine_market_details: {e}")
        import traceback
        traceback.print_exc()
        abort(404)


@app.route('/raw/<id>')
def raw_medicine(id):
    """Route pour voir les données brutes d'un médicament en JSON"""
    try:
        medicine = collection.find_one({'_id': ObjectId(id)})
        if not medicine:
            abort(404)
        return jsonify(json.loads(json_util.dumps(medicine)))
    except:
        abort(404)

@app.route('/debug')
def debug_info():
    """Page de debug pour afficher la structure de la base de données"""
    collection_stats = db.command("collStats", "medicines")
    sample_doc = collection.find_one()
    sample_json = json_util.dumps(sample_doc, indent=2)
    
    # Liste des champs présents dans les documents
    fields = set()
    for doc in collection.find().limit(100):
        fields.update(doc.keys())
    
    # Get filter options
    available_filters = extract_filter_options()
    
    return render_template('debug.html', 
                          stats=collection_stats,
                          sample=sample_json,
                          fields=sorted(list(fields)),
                          available_filters=available_filters)

@app.route("/api/search-results")
def search_results_api():
    """
    Recherche V3 (niveau medicine_market), avec filtres + pagination.
    Retour JSON compatible classic_search.html :
    - results[] contient id/title/update_date/medicine_details...
    """
    try:
        search_query = (request.args.get("search", "") or "").strip()

        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))

        # filtres du front (noms existants)
        substance = (request.args.get("substance", "") or "").strip()
        forme = (request.args.get("forme", "") or "").strip()
        laboratoire = (request.args.get("laboratoire", "") or "").strip()
        dosage = (request.args.get("dosage", "") or "").strip()

        # Filtre par sources de données (nouveau)
        sources = request.args.getlist("sources")  # Array: ['ANSM', 'PharmGKB', etc.]

        # Filtre grossesse/allaitement
        grossesse_filter = (request.args.get("grossesse", "") or "").strip()
        # Valeurs possibles: "compatible", "danger", "" (pas de filtre)
        
        # optionnel (si tu ajoutes un filtre pays plus tard)
        country = (request.args.get("country", "") or "").strip()

        # Tri par défaut alphabétique (A-Z)
        sort_option = (request.args.get("sort", "name_asc") or "name_asc").strip()

        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 10
        if per_page > 100:
            per_page = 100

        match_filters = []

        # -----------------------------
        # (A) Recherche libre
        # -----------------------------
        if search_query:
            rgx = {"$regex": search_query, "$options": "i"}

            # match direct côté market
            market_or = [
                {"brand_title": rgx},
                {"cis": rgx},
                {"laboratory": rgx},
                {"form": rgx},
                {"strength": rgx},
                {"country": rgx},
                {"medicine_id": rgx},
            ]

            # match côté medicines_v3 -> medicine_ref
            med_ids_from_meds = list(
                medicines_v3.find(
                    {"$or": [{"medicine_key": rgx}, {"inns": rgx}, {"substance_labels": rgx}]},
                    {"_id": 1},
                ).limit(3000)
            )
            med_ids_from_meds = [d["_id"] for d in med_ids_from_meds]

            # match côté substances_v3 -> medicines_v3 -> market
            sub_ids = list(
                substances_v3.find(
                    {"$or": [{"label": rgx}, {"label_normalized": rgx}]},
                    {"_id": 1},
                ).limit(1500)
            )
            sub_ids = [d["_id"] for d in sub_ids]

            med_ids_from_subs = []
            if sub_ids:
                med_ids_from_subs_docs = list(
                    medicines_v3.find(
                        {"substance_ref_ids": {"$in": sub_ids}},
                        {"_id": 1},
                    ).limit(5000)
                )
                med_ids_from_subs = [d["_id"] for d in med_ids_from_subs_docs]

            med_ids_union = list({*med_ids_from_meds, *med_ids_from_subs})

            # combine
            or_all = [{"$or": market_or}]
            if med_ids_union:
                or_all.append({"medicine_ref": {"$in": med_ids_union}})

            match_filters.append({"$or": or_all})

        # -----------------------------
        # (B) Filtre Substance (select)
        # -----------------------------
        if substance:
            rgx_sub = {"$regex": substance, "$options": "i"}
            sub_ids = list(
                substances_v3.find(
                    {"$or": [{"label": rgx_sub}, {"label_normalized": rgx_sub}]},
                    {"_id": 1},
                ).limit(1500)
            )
            sub_ids = [d["_id"] for d in sub_ids]

            if not sub_ids:
                return jsonify({"results": [], "has_more": False, "total_results": 0, "total_pages": 0})

            med_ids = list(
                medicines_v3.find(
                    {"substance_ref_ids": {"$in": sub_ids}},
                    {"_id": 1},
                ).limit(8000)
            )
            med_ids = [d["_id"] for d in med_ids]

            if not med_ids:
                return jsonify({"results": [], "has_more": False, "total_results": 0, "total_pages": 0})

            match_filters.append({"medicine_ref": {"$in": med_ids}})

        # -----------------------------
        # (C) Filtres market
        # -----------------------------
        if forme:
            match_filters.append({"form": {"$regex": forme, "$options": "i"}})

        if laboratoire:
            match_filters.append({"laboratory": {"$regex": laboratoire, "$options": "i"}})

        if dosage:
            match_filters.append({"strength": {"$regex": dosage, "$options": "i"}})

        if country:
            match_filters.append({"country": {"$regex": f"^{country}$", "$options": "i"}})
        
        # -----------------------------
        # (D) Filtre par sources de données
        # -----------------------------
        if sources and len(sources) > 0:
            # Filtrer les médocs qui ont AU MOINS une des sources sélectionnées
            match_filters.append({"data_sources": {"$in": sources}})

        # -----------------------------
        # (E) Filtre Grossesse / Allaitement
        # -----------------------------
        if grossesse_filter == "compatible":
            # Exclure les médicaments dont la section 4.6 contient "contre-indiqué"
            # Ne garder que les FR avec RCP (les autres n'ont pas de section 4.6)
            match_filters.append({"country": "FR"})
            match_filters.append({"rcp.sections": {"$exists": True}})
            # Exclure ceux avec contre-indication formelle dans les sous-sections grossesse
            match_filters.append({
                "rcp.sections.subsections.content.text": {
                    "$not": {"$regex": "contre-indiqu", "$options": "i"}
                }
            })
        elif grossesse_filter == "danger":
            # Garder uniquement les médicaments contre-indiqués pendant la grossesse
            match_filters.append({"country": "FR"})
            match_filters.append({"rcp.sections": {"$exists": True}})
            match_filters.append({
                "rcp.sections.subsections.content.text": {
                    "$regex": "contre-indiqu", "$options": "i"
                }
            })

        query = {"$and": match_filters} if match_filters else {}

        # -----------------------------
        # Comptage + pagination
        # -----------------------------
        total_results = medicine_market.count_documents(query)

        # tri avec priorités: correspondance exacte, FR + RCP/ANSM, puis alphabétique
        if sort_option == "name_asc":
            # Système de priorité multi-niveaux avec correspondance recherche
            add_fields = {
                "is_french": {"$eq": ["$country", "FR"]},
                "has_rcp": {
                    "$or": [
                        {"$gt": [{"$size": {"$ifNull": [{"$objectToArray": "$rcp"}, []]}}, 0]},
                        {"$regexMatch": {"input": {"$ifNull": [{"$arrayElemAt": ["$source_urls", 0]}, ""]}, "regex": "base-donnees-publique.medicaments.gouv.fr", "options": "i"}}
                    ]
                },
                "starts_with_letter": {"$regexMatch": {"input": "$brand_title", "regex": "^[A-Za-zÀ-ÿ]"}},
                # Calcul de la priorité combinée
                "country_priority": {
                    "$switch": {
                        "branches": [
                            # Priorité 1: FR + RCP
                            {"case": {"$and": [{"$eq": ["$country", "FR"]}, {"$or": [{"$gt": [{"$size": {"$ifNull": [{"$objectToArray": "$rcp"}, []]}}, 0]}, {"$regexMatch": {"input": {"$ifNull": [{"$arrayElemAt": ["$source_urls", 0]}, ""]}, "regex": "base-donnees-publique.medicaments.gouv.fr", "options": "i"}}]}]}, "then": 1},
                            # Priorité 2: FR sans RCP
                            {"case": {"$eq": ["$country", "FR"]}, "then": 2},
                            # Priorité 3: Autres pays avec RCP
                            {"case": {"$or": [{"$gt": [{"$size": {"$ifNull": [{"$objectToArray": "$rcp"}, []]}}, 0]}, {"$regexMatch": {"input": {"$ifNull": [{"$arrayElemAt": ["$source_urls", 0]}, ""]}, "regex": "base-donnees-publique.medicaments.gouv.fr", "options": "i"}}]}, "then": 3}
                        ],
                        # Priorité 4: Autres
                        "default": 4
                    }
                },
                "letter_priority": {
                    "$cond": {
                        "if": {"$regexMatch": {"input": "$brand_title", "regex": "^[A-Za-zÀ-ÿ]"}},
                        "then": 0,  # Lettres en premier
                        "else": 1   # Caractères spéciaux après
                    }
                }
            }
            
            # Si une recherche est active, ajouter la priorité de correspondance
            if search_query:
                # Priorité de correspondance: 0 = commence par le terme, 1 = contient le terme
                add_fields["match_priority"] = {
                    "$cond": {
                        "if": {"$regexMatch": {"input": "$brand_title", "regex": f"^{search_query}", "options": "i"}},
                        "then": 0,  # Commence par le terme recherché
                        "else": 1   # Contient le terme recherché
                    }
                }
                sort_spec = {"match_priority": 1, "country_priority": 1, "letter_priority": 1, "brand_title": 1}
            else:
                sort_spec = {"country_priority": 1, "letter_priority": 1, "brand_title": 1}
            
            pipeline = [
                {"$match": query},
                {"$addFields": add_fields},
                {"$sort": sort_spec},
                {"$skip": (page - 1) * per_page},
                {"$limit": per_page}
            ]
            market_docs = list(medicine_market.aggregate(pipeline))
        elif sort_option == "name_desc":
            # Tri descendant avec priorités et correspondance recherche
            add_fields = {
                "country_priority": {
                    "$switch": {
                        "branches": [
                            {"case": {"$and": [{"$eq": ["$country", "FR"]}, {"$or": [{"$gt": [{"$size": {"$ifNull": [{"$objectToArray": "$rcp"}, []]}}, 0]}, {"$regexMatch": {"input": {"$ifNull": [{"$arrayElemAt": ["$source_urls", 0]}, ""]}, "regex": "base-donnees-publique.medicaments.gouv.fr", "options": "i"}}]}]}, "then": 1},
                            {"case": {"$eq": ["$country", "FR"]}, "then": 2},
                            {"case": {"$or": [{"$gt": [{"$size": {"$ifNull": [{"$objectToArray": "$rcp"}, []]}}, 0]}, {"$regexMatch": {"input": {"$ifNull": [{"$arrayElemAt": ["$source_urls", 0]}, ""]}, "regex": "base-donnees-publique.medicaments.gouv.fr", "options": "i"}}]}, "then": 3}
                        ],
                        "default": 4
                    }
                },
                "letter_priority": {
                    "$cond": {
                        "if": {"$regexMatch": {"input": "$brand_title", "regex": "^[A-Za-zÀ-ÿ]"}},
                        "then": 0,
                        "else": 1
                    }
                }
            }
            
            # Si une recherche est active, ajouter la priorité de correspondance
            if search_query:
                add_fields["match_priority"] = {
                    "$cond": {
                        "if": {"$regexMatch": {"input": "$brand_title", "regex": f"^{search_query}", "options": "i"}},
                        "then": 0,  # Commence par le terme recherché
                        "else": 1   # Contient le terme recherché
                    }
                }
                sort_spec = {"match_priority": 1, "country_priority": 1, "letter_priority": 1, "brand_title": -1}
            else:
                sort_spec = {"country_priority": 1, "letter_priority": 1, "brand_title": -1}
            
            pipeline = [
                {"$match": query},
                {"$addFields": add_fields},
                {"$sort": sort_spec},
                {"$skip": (page - 1) * per_page},
                {"$limit": per_page}
            ]
            market_docs = list(medicine_market.aggregate(pipeline))
        else:
            # Tri par date (pas besoin d'aggregation)
            if sort_option == "date_asc":
                sort_spec = [("updated_at", 1)]
            else:
                sort_spec = [("updated_at", -1)]  # date_desc
            
            cursor = (
                medicine_market.find(query)
                .sort(sort_spec)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )
            market_docs = list(cursor)

        # -----------------------------
        # hydrate medicines_v3 + substances_v3
        # -----------------------------
        med_ids = list({d.get("medicine_ref") for d in market_docs if d.get("medicine_ref")})
        meds_map = {}
        subs_map = {}

        if med_ids:
            meds = list(medicines_v3.find({"_id": {"$in": med_ids}}))
            meds_map = {m["_id"]: m for m in meds}

            all_sub_ids = []
            for m in meds:
                for sid in (m.get("substance_ref_ids") or []):
                    all_sub_ids.append(sid)
            all_sub_ids = list({*all_sub_ids})

            if all_sub_ids:
                subs = list(substances_v3.find({"_id": {"$in": all_sub_ids}}))
                subs_map = {s["_id"]: s for s in subs}

        def ts_to_date(ts):
            try:
                return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
            except Exception:
                return "Non disponible"

        results = []
        for mk in market_docs:
            med = meds_map.get(mk.get("medicine_ref")) or {}

            source_tags = set()

            # BDPM/ANSM (RCP)
            for u in (mk.get("source_urls") or []):
                if isinstance(u, str) and "base-donnees-publique.medicaments.gouv.fr" in u.lower():
                    source_tags.add("BDPM/ANSM")

            # PubChem / DrugBank via substances
            for sid in (med.get("substance_ref_ids") or []):
                sdoc = subs_map.get(sid)
                if not sdoc:
                    continue
                src = sdoc.get("sources") or {}
                if "pubchem" in src:
                    source_tags.add("PubChem")
                if "drugbank" in src:
                    source_tags.add("DrugBank")
                if "openfda" in src:
                    source_tags.add("OpenFDA")
                if "theriaque" in src:
                    source_tags.add("Thériaque")


            # substances affichées
            subs_labels = []

            # 1) priorité aux labels déjà présents dans medicines_v3
            raw_labels = med.get("substance_labels") or []
            subs_labels = [x for x in raw_labels if isinstance(x, str) and x.strip()]

            # 2) sinon via refs ObjectId vers substances_v3
            if not subs_labels:
                for sid in (med.get("substance_ref_ids") or []):
                    sdoc = subs_map.get(sid)
                    if sdoc and isinstance(sdoc.get("label"), str) and sdoc["label"].strip():
                        subs_labels.append(sdoc["label"].strip())

            # 3) dernière sécurité
            if not subs_labels:
                subs_labels = ["Non disponible"]


            # sources (simple) depuis source_urls
            srcs = []
            for u in (mk.get("source_urls") or []):
                if isinstance(u, str) and u.strip():
                    srcs.append(u)
            srcs = srcs[:3]

            substances_clean = []
            for x in subs_labels:
                if not isinstance(x, str):
                    continue
                x = x.strip()
                if x and x not in substances_clean:
                    substances_clean.append(x)

            # ✅ Classification grossesse/allaitement depuis RCP 4.6
            pregnancy_info = None
            rcp_raw = mk.get("rcp")
            if rcp_raw and isinstance(rcp_raw, dict) and rcp_raw.get("sections"):
                try:
                    preg = classify_pregnancy_breastfeeding(rcp_raw)
                    if preg.get("has_data"):
                        pregnancy_info = {
                            "global_level": preg["global_level"],
                            "grossesse": preg["grossesse"]["level"],
                            "allaitement": preg["allaitement"]["level"],
                        }
                except Exception:
                    pass

            results.append({
                "id": mk.get("market_key") or mk.get("_id"),  # utiliser market_key pour éviter les / dans les URLs
                "title": mk.get("brand_title") or mk.get("medicine_id") or str(mk.get("_id")),
                "update_date": ts_to_date(mk.get("updated_at")),
                "pregnancy_info": pregnancy_info,
                "medicine_details": {
                    "forme": mk.get("form") or "Non spécifié",
                    "dosages": [mk.get("strength")] if mk.get("strength") else [],

                    # ✅ compat front (classic_search.html lit "substances_actives")
                    "substances_actives": substances_clean[:4] if substances_clean else ["Non disponible"],

                    # (optionnel) tu peux garder aussi "substances" si tu veux
                    "substances": substances_clean[:4] if substances_clean else ["Non disponible"],


                    # nouveaux champs (pour UI plus riche)
                    "substances_preview": substances_clean[:4] if substances_clean else ["Non disponible"],
                    "substances_count": len(substances_clean),
                    "substances_all": substances_clean[:50],

                    "laboratoire": mk.get("laboratory") or "Non spécifié",
                    "date": ts_to_date(mk.get("updated_at")),

                    # legacy: source (le front affiche ça) -> tag si possible sinon URL
                    "source": (sorted(source_tags)[0] if source_tags else ((mk.get("source_urls") or ["Non disponible"])[0])),

                    # nouveaux champs sources
                    "sources": sorted(source_tags) if source_tags else ["Non disponible"],
                    "source_urls": (mk.get("source_urls") or [])[:3],

                    "country": mk.get("country") or "Non spécifié",
                    "cis": mk.get("cis") or "Non disponible",
                },
                "debug_substance_link": {
                    "market_id": mk.get("_id"),
                    "medicine_ref": str(mk.get("medicine_ref")) if mk.get("medicine_ref") else None,
                    "medicine_has_substance_labels": bool(med.get("substance_labels")),
                    "medicine_substance_ref_ids_count": len(med.get("substance_ref_ids") or []),
                }
            })



        total_pages = (total_results + per_page - 1) // per_page
        has_more = page < total_pages

        return jsonify({
            "results": results,
            "has_more": has_more,
            "total_results": total_results,
            "total_pages": total_pages
        })

    except Exception as e:
        print(f"[api/search-results V3] erreur: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/search-results-stream')
def search_results_api_stream():
    search_query = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    substance = request.args.get('substance', '')
    forme = request.args.get('forme', '')
    laboratoire = request.args.get('laboratoire', '')
    dosage = request.args.get('dosage', '')
    sort_option = request.args.get('sort', 'date_desc')

    query = {}
    pipeline_filters = []

    # Construction de la requête de recherche
    if search_query:
        search_regex = {'$regex': search_query, '$options': 'i'}

        pipeline_filters.append({'$or': [
            # --- v2 (nouveau schéma)
            {'drug.name': search_regex},
            {'drug.full_title': search_regex},
            {'drug.active_substances': search_regex},
            {'rcp.search_text': search_regex},
            {'rcp.sections.title': search_regex},
            {'rcp.sections.blocks.text': search_regex},
            {'rcp.sections.subsections.title': search_regex},
            {'rcp.sections.subsections.content.text': search_regex},

            # --- v1 (ancien schéma)
            {'title': search_regex},
            {'medicine_details.substances_actives': search_regex},
            {'sections.content': search_regex},
            {'sections.subsections.content': search_regex},
            {'sections.subsections.subsections.content': search_regex},
        ]})
    if substance:
        pipeline_filters.append({'$or': [
            {'drug.active_substances': {'$regex': substance, '$options': 'i'}},
            {'medicine_details.substances_actives': {'$regex': substance, '$options': 'i'}},
        ]})

    if forme:
        pipeline_filters.append({'$or': [
            {'drug.form': {'$regex': forme, '$options': 'i'}},
            {'medicine_details.forme': {'$regex': forme, '$options': 'i'}},
        ]})

    if laboratoire:
        pipeline_filters.append({'$or': [
            {'drug.laboratory': {'$regex': laboratoire, '$options': 'i'}},
            {'medicine_details.laboratoire': {'$regex': laboratoire, '$options': 'i'}},
        ]})

    if dosage:
        pipeline_filters.append({'$or': [
            {'drug.strengths': {'$regex': dosage, '$options': 'i'}},
            {'medicine_details.dosages': {'$regex': dosage, '$options': 'i'}},
        ]})

    # Combiner les filtres avec $and
    if pipeline_filters:
        query['$and'] = pipeline_filters

    def generate():
        formatted_results = []
        total_results = collection.count_documents(query) # Calculer le nombre total de résultats
        
        # Envoyer le nombre total de résultats
        total_update = json.dumps({'total': total_results})
        yield f"event: total\ndata: {total_update}\n\n"

        medicines = collection.find(query).skip((page - 1) * per_page).limit(per_page) # Charger les résultats par page
        
        result_count = 0
        for medicine in medicines:
            if search_query:
                relevance_score = calculate_relevance_score(medicine, search_query)
                medicine['search_matches'] = find_search_term_locations(medicine, search_query)
            else:
                relevance_score = 0
                medicine['search_matches'] = []
            
            formatted_result = {
                'id': str(medicine['_id']),
                'title': medicine['title'],
                'update_date': medicine.get('update_date', 'Non disponible'),
                'medicine_details': medicine.get('medicine_details', {}),
                'relevance_score': relevance_score,
                'match_count': medicine.get('match_count', 0),
                'search_matches': medicine['search_matches']
            }
            
            
            json_result = json.dumps(formatted_results[-1], ensure_ascii=False)
            
            # Envoyer le résultat via le flux d'événements
            yield f"data: {json_result}\n\n"
            
            result_count += 1
            
            # Envoyer la mise à jour du compteur
            count_update = json.dumps({'count': result_count})
            yield f"event: count\ndata: {count_update}\n\n"

        # Envoyer un événement de fin de flux
        yield "data: end\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# Ajout de la page d'erreur 404
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

# Ajout de la page d'erreur 500
@app.errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500

# Fonction pour créer un context processor qui sera disponible dans tous les templates
@app.context_processor
def inject_user_and_date():
    return {
        'user': g.get('user', None),
        'now': datetime.now()
    }

@app.route('/api/toggle-favorite/<medicine_id>', methods=['POST'])
def toggle_favorite(medicine_id):
    """Ajoute ou supprime un médicament des favoris de l'utilisateur connecté"""
    # Vérifier si l'utilisateur est connecté
    if 'user_id' not in request.cookies:
        return jsonify({"success": False, "message": "Utilisateur non connecté"}), 401
    
    user_id = request.cookies.get('user_id')
    
    try:
        # Vérifier si le médicament existe
        medicine = collection.find_one({'_id': ObjectId(medicine_id)})
        if not medicine:
            return jsonify({"success": False, "message": "Médicament non trouvé"}), 404
        
        from models import Interaction
        
        # Vérifier si le médicament est déjà un favori
        if Interaction.is_favorite(user_id, medicine_id):
            # Supprimer des favoris
            if Interaction.remove_favorite(user_id, medicine_id):
                return jsonify({"success": True, "is_favorite": False})
            else:
                return jsonify({"success": False, "message": "Erreur lors de la suppression des favoris"}), 500
        else:
            # Ajouter aux favoris
            if Interaction.add_favorite(user_id, medicine_id):
                return jsonify({"success": True, "is_favorite": True})
            else:
                return jsonify({"success": False, "message": "Erreur lors de l'ajout aux favoris"}), 500
    except Exception as e:
        print(f"Erreur lors de la gestion des favoris: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    

@app.route("/market/<path:market_id>")
def market_details_v3(market_id):
    """
    Ancienne route - Redirige vers la nouvelle route moderne /medicine-market/
    """
    return redirect(url_for('medicine_market_details', id=market_id))

@app.route('/api/medicine-summary/<id>')
def get_medicine_summary(id):
    """API endpoint to get the AI summary of a medicine"""
    try:
        print(f"🔍 API - Recherche du résumé pour ID: {id}")
        
        # Try to convert to ObjectId, or use as string if it fails
        try:
            medicine_id = ObjectId(id)
            print(f"✅ ID converti en ObjectId: {medicine_id}")
        except:
            medicine_id = id
            print(f"⚠️  ID utilisé comme string: {medicine_id}")
        
        # First check in medicines collection
        stored_medicine = db.medicines.find_one(
            {'_id': medicine_id},
            {'ai_summary': 1}
        )
        
        # If not found, check in medicine_market collection
        if not stored_medicine:
            print(f"🔍 Recherche dans medicine_market...")
            stored_medicine = db.medicine_market.find_one(
                {'_id': medicine_id},
                {'ai_summary': 1}
            )
        
        print(f"📊 Médicament trouvé: {stored_medicine is not None}")
        if stored_medicine:
            print(f"📝 A un résumé: {'ai_summary' in stored_medicine and stored_medicine['ai_summary']}")
        
        if stored_medicine and 'ai_summary' in stored_medicine and stored_medicine['ai_summary']:
            print(f"✅ Résumé trouvé et retourné")
            return jsonify({
                "success": True,
                "summary": stored_medicine['ai_summary']
            })
        
        # If not, the summary is being generated in the background
        # Return empty for now, the JS will retry
        print(f"⏳ Résumé en cours de génération...")
        return jsonify({
            "success": True,
            "summary": None
        })
    except Exception as e:
        print(f"❌ Error retrieving medicine summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/ai-search', methods=['GET', 'POST'])
def ai_search():
    """Recherche IA avec reformulation et synthèse via Mistral"""
    user_query = ''
    reformulated_query = ''
    ai_answer = ''
    results = []
    total = 0

    if request.method == 'POST':
        user_query = request.form.get('query', '').strip()
        if user_query:
            # 1. Reformuler la question avec Mistral
            reformulated_query = call_mistral_reformulate(user_query)

            # 2. Générer l'embedding
            embedding = embedding_model.encode(reformulated_query).tolist()

            # 3. Recherche vectorielle Qdrant avec query_points -> QueryResponse.points
            qdrant_response = qdrant_client.query_points(
                collection_name="medicaments",
                query=embedding,
                limit=5
            )
            search_results = qdrant_response.points or []

            # 4. Récupérer les documents (payloads) et inclure le score
            docs = []
            for hit in search_results:
                payload = getattr(hit, "payload", {}) or {}
                doc = dict(payload)
                doc['score'] = getattr(hit, 'score', None)
                docs.append(doc)
            results = docs
            total = len(results)

            # 5. Générer la réponse IA
            ai_answer = call_mistral_summarize(user_query, docs)

    return render_template(
        "AI_search.html",
        query=user_query,
        reformulated_query=reformulated_query,
        ai_answer=ai_answer,
        results=results,
        total=total,
        initial_count=5
    )

###############################################################################
# ─── DASHBOARD ── Tableau de bord de l'entrepôt de données ───────────────────
###############################################################################

@app.route('/dashboard')
def dashboard():
    """Dashboard statistiques de l'entrepôt de données médicamenteuses"""
    try:
        # ── 1) Compteurs globaux ──
        total_market       = medicine_market.count_documents({})
        total_medicines    = medicines_v3.count_documents({})
        total_substances   = substances_v3.count_documents({})
        total_labs         = len(medicine_market.distinct("laboratory", {"laboratory": {"$nin": [None, ""]}}))
        total_pharmgkb     = db.pharmgkb_drugs.count_documents({})
        total_pgkb_rels    = db.pharmgkb_relationships.count_documents({})
        total_drugbank     = db.drugbank_raw_chunks.count_documents({})
        total_interactions = db.drugbank_raw_chunks.count_documents({'kind': 'drug-interactions'})

        # ── 2) Répartition par pays (tous) ──
        countries_pipeline = [
            {"$match": {"country": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$country", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        countries_raw = list(medicine_market.aggregate(countries_pipeline))
        countries_data = [{"country": d["_id"], "count": d["count"]} for d in countries_raw]

        # ── 3) Top 15 laboratoires ──
        labs_pipeline = [
            {"$match": {"laboratory": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$laboratory", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 15}
        ]
        labs_data = [{"lab": d["_id"], "count": d["count"]} for d in medicine_market.aggregate(labs_pipeline)]

        # ── 4) Sources de données (basé sur data_sources) ──
        source_labels = ["ANSM", "Theriaque", "DrugBank", "PubChem", "PharmGKB", "OpenFDA", "EMA"]
        sources_data = []
        for label in source_labels:
            c = medicine_market.count_documents({"data_sources": {"$regex": f"^{label}$", "$options": "i"}})
            if c > 0:
                sources_data.append({"source": label, "count": c})

        # ── 5) Top 20 substances (les plus présentes dans medicines via substance_ref_ids) ──
        top_subs_pipeline = [
            {"$unwind": "$substance_ref_ids"},
            {"$group": {"_id": "$substance_ref_ids", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
            {"$lookup": {
                "from": "substances_v3",
                "localField": "_id",
                "foreignField": "_id",
                "as": "sub"
            }},
            {"$unwind": {"path": "$sub", "preserveNullAndEmptyArrays": True}},
            {"$project": {
                "label": {"$ifNull": ["$sub.label", "Inconnue"]},
                "count": 1
            }}
        ]
        top_substances = [
            {"label": d.get("label", "Inconnue"), "count": d["count"]}
            for d in medicines_v3.aggregate(top_subs_pipeline)
        ]

        # ── 6) PharmGKB – top 15 gènes les plus fréquents ──
        genes_pipeline = [
            {"$match": {"gene_symbol": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$gene_symbol", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 15}
        ]
        top_genes = [{"gene": d["_id"], "count": d["count"]} for d in db.pharmgkb_relationships.aggregate(genes_pipeline)]

        # ── 7) DrugBank – répartition des chunks par type ──
        chunks_pipeline = [
            {"$group": {"_id": "$kind", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        chunks_by_kind = [{"kind": d["_id"], "count": d["count"]} for d in db.drugbank_raw_chunks.aggregate(chunks_pipeline)]

        # ── 8) PharmGKB – répartition par type d'association ──
        assoc_pipeline = [
            {"$match": {"association": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$association", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        assoc_data = [{"type": d["_id"], "count": d["count"]} for d in db.pharmgkb_relationships.aggregate(assoc_pipeline)]

        # ── 9) PharmGKB – PK vs PD ──
        pk_count = db.pharmgkb_relationships.count_documents({"pk": {"$nin": [None, ""]}})
        pd_count = db.pharmgkb_relationships.count_documents({"pd": {"$nin": [None, ""]}})

        # ── 10) Derniers ajouts market ──
        latest_raw = medicine_market.find(
            {},
            {"brand_title": 1, "country": 1, "laboratory": 1, "updated_at": 1}
        ).sort([("updated_at", -1)]).limit(10)
        latest = [
            {
                "brand_title": d.get("brand_title", ""),
                "country": d.get("country", ""),
                "laboratory": d.get("laboratory", ""),
                "updated_at": str(d.get("updated_at", ""))
            }
            for d in latest_raw
        ]

        # ── 11) Formes galéniques top 10 ──
        forms_pipeline = [
            {"$match": {"form": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$form", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        top_forms = [{"form": d["_id"], "count": d["count"]} for d in medicine_market.aggregate(forms_pipeline)]

        return render_template(
            'dashboard.html',
            total_market=total_market,
            total_medicines=total_medicines,
            total_substances=total_substances,
            total_labs=total_labs,
            total_pharmgkb=total_pharmgkb,
            total_pgkb_rels=total_pgkb_rels,
            total_drugbank=total_drugbank,
            total_interactions=total_interactions,
            countries_data=countries_data,
            labs_data=labs_data,
            sources_data=sources_data,
            top_substances=top_substances,
            top_genes=top_genes,
            chunks_by_kind=chunks_by_kind,
            assoc_data=assoc_data,
            pk_count=pk_count,
            pd_count=pd_count,
            latest=latest,
            top_forms=top_forms,
        )
    except Exception as e:
        print(f"Erreur dashboard: {e}")
        import traceback
        traceback.print_exc()
        abort(500)


###############################################################################
# ─── INTERACTION CHECKER ── Vérificateur d'interactions multi-médicaments ────
###############################################################################

@app.route('/interaction-checker')
def interaction_checker():
    """Page du vérificateur d'interactions médicamenteuses"""
    return render_template('interaction_checker.html')


@app.route('/api/interaction-checker/search-drugs', methods=['GET'])
def interaction_checker_search_drugs():
    """API autocomplete : cherche des médicaments/substances pour le checker"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])

    results = []
    seen = set()
    escaped = re.escape(query)

    # 1) Chercher dans substances_v3 (priorité — noms internationaux)
    for sub in substances_v3.find(
        {'$or': [
            {'label': {'$regex': escaped, '$options': 'i'}},
            {'label_normalized': {'$regex': escaped.upper()}},
        ]},
        {'label': 1, 'label_normalized': 1, 'sources.drugbank.drugbank_id': 1}
    ).limit(15):
        drugbank_id = (sub.get('sources') or {}).get('drugbank', {}).get('drugbank_id')
        label = sub.get('label', sub.get('label_normalized', ''))
        key = label.lower()
        if key not in seen and drugbank_id:
            seen.add(key)
            results.append({
                'id': str(sub['_id']),
                'label': label,
                'type': 'substance',
                'drugbank_id': drugbank_id
            })

    # 2) Chercher dans medicine_market (noms commerciaux)
    for med in medicine_market.find(
        {'brand_title': {'$regex': escaped, '$options': 'i'}},
        {'brand_title': 1, 'medicine_ref': 1, 'country': 1, 'laboratory': 1, 'medicine_id': 1}
    ).limit(10):
        label = med.get('brand_title', '')
        key = label.lower()
        if key not in seen:
            seen.add(key)
            results.append({
                'id': str(med['_id']),
                'label': label,
                'type': 'medicine',
                'country': med.get('country', ''),
                'laboratory': med.get('laboratory', ''),
                'medicine_ref': str(med.get('medicine_ref', '')),
                'medicine_id': med.get('medicine_id', '')
            })

    return jsonify(results[:20])


def _resolve_drugbank_id(item):
    """Résout le drugbank_id d'un item (substance ou médicament market)"""
    # Si c'est une substance avec drugbank_id direct
    if item.get('drugbank_id'):
        return item['drugbank_id'], item.get('label', '')

    def _find_substance_with_drugbank(name):
        """Cherche une substance ayant un DrugBank ID via label, legacy ou synonymes PubChem"""
        if not name:
            return None, None
        escaped = re.escape(name)
        # 1) Par label direct
        sub = substances_v3.find_one({
            '$or': [
                {'label': {'$regex': f'^{escaped}$', '$options': 'i'}},
                {'label_normalized': name.upper()},
            ],
            'sources.drugbank.drugbank_id': {'$exists': True}
        })
        if sub:
            dbid = sub['sources']['drugbank']['drugbank_id']
            return dbid, sub.get('label', name)
        # 2) Par legacy.substances_id (DCI français → substance anglaise avec DrugBank)
        sub = substances_v3.find_one({
            'legacy.substances_id': {'$regex': f'^{escaped}$', '$options': 'i'},
            'sources.drugbank.drugbank_id': {'$exists': True}
        })
        if sub:
            dbid = sub['sources']['drugbank']['drugbank_id']
            return dbid, sub.get('label', name)
        # 3) Par synonymes PubChem
        sub = substances_v3.find_one({
            'sources.pubchem.synonyms_top': {'$regex': f'^{escaped}$', '$options': 'i'},
            'sources.drugbank.drugbank_id': {'$exists': True}
        })
        if sub:
            dbid = sub['sources']['drugbank']['drugbank_id']
            return dbid, sub.get('label', name)
        # 4) Recherche partielle : extraire le mot-clé le plus long (sans accents) pour match fuzzy
        import unicodedata
        def _strip_accents(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        words = re.sub(r'[^a-zA-ZÀ-ÿ\s]', '', name).split()
        longest = max(words, key=len) if words else ''
        if len(longest) >= 6:
            prefix = _strip_accents(longest)[:7]
            sub = substances_v3.find_one({
                'label': {'$regex': prefix, '$options': 'i'},
                'sources.drugbank.drugbank_id': {'$exists': True}
            })
            if sub:
                dbid = sub['sources']['drugbank']['drugbank_id']
                return dbid, sub.get('label', name)
        return None, None

    # Si c'est un médicament market, retrouver la substance active principale
    if item.get('type') == 'medicine':
        # Stratégie A : utiliser medicine_id (DCI / INN) du document market
        medicine_id = item.get('medicine_id', '')
        if medicine_id:
            dbid, label = _find_substance_with_drugbank(medicine_id)
            if dbid:
                return dbid, label or item.get('label', '')

        # Stratégie B : aller via medicine_ref -> medicines_v3 -> substances
        if item.get('medicine_ref'):
            try:
                med = medicines_v3.find_one({'_id': ObjectId(item['medicine_ref'])})
                if med:
                    # Essayer les inns (DCI international)
                    for inn in (med.get('inns') or []):
                        if inn:
                            dbid, label = _find_substance_with_drugbank(inn)
                            if dbid:
                                return dbid, label or item.get('label', '')

                    # Essayer substance_labels
                    for slabel in (med.get('substance_labels') or []):
                        if slabel:
                            dbid, label = _find_substance_with_drugbank(slabel)
                            if dbid:
                                return dbid, label or item.get('label', '')

                    # Fallback : essayer les substance_ref_ids
                    sub_refs = med.get('substance_refs', []) or med.get('substance_ref_ids', [])
                    for ref in sub_refs:
                        sub = substances_v3.find_one({'_id': ref})
                        if not sub:
                            try:
                                sub = substances_v3.find_one({'_id': ObjectId(str(ref))})
                            except Exception:
                                pass
                        if sub:
                            dbid = (sub.get('sources') or {}).get('drugbank', {}).get('drugbank_id')
                            if dbid:
                                return dbid, sub.get('label', item.get('label', ''))
            except Exception:
                pass

    # Fallback : chercher la substance par nom (brand label)
    label = item.get('label', '')
    if label:
        dbid, found_label = _find_substance_with_drugbank(label)
        if dbid:
            return dbid, found_label or label

    return None, label


@app.route('/api/interaction-checker/check', methods=['POST'])
def interaction_checker_check():
    """
    API principale : vérifie les interactions croisées entre N médicaments.
    Body JSON : { "drugs": [ {id, label, type, drugbank_id?, medicine_ref?}, ... ] }
    """
    data = request.get_json(silent=True)
    if not data or 'drugs' not in data:
        return jsonify({'error': 'Données invalides'}), 400

    drugs = data['drugs']
    if len(drugs) < 2:
        return jsonify({'error': 'Sélectionnez au moins 2 médicaments'}), 400
    if len(drugs) > 10:
        return jsonify({'error': 'Maximum 10 médicaments simultanés'}), 400

    # 1) Résoudre les DrugBank IDs
    drug_map = {}  # drugbank_id -> {label, ...}
    for drug in drugs:
        dbid, label = _resolve_drugbank_id(drug)
        if dbid:
            drug_map[dbid] = {
                'drugbank_id': dbid,
                'label': label or drug.get('label', dbid),
                'original': drug
            }

    if len(drug_map) < 2:
        return jsonify({
            'error': 'Impossible de résoudre les identifiants DrugBank pour au moins 2 des médicaments sélectionnés.',
            'resolved_count': len(drug_map)
        }), 400

    # 2) Pour chaque drug, récupérer TOUTES ses interactions
    all_interactions = {}  # drugbank_id -> list[{name, drugbank-id, description}]
    for dbid in drug_map:
        chunks = list(db.drugbank_raw_chunks.find({
            'drugbank_id': dbid,
            'kind': 'drug-interactions'
        }))
        interactions = []
        for chunk in chunks:
            if chunk.get('data') and isinstance(chunk['data'], list):
                interactions.extend(chunk['data'])
        all_interactions[dbid] = interactions

    # 3) Détecter les interactions croisées
    cross_interactions = []
    dbids = list(drug_map.keys())

    for i in range(len(dbids)):
        for j in range(i + 1, len(dbids)):
            id_a = dbids[i]
            id_b = dbids[j]
            label_a = drug_map[id_a]['label']
            label_b = drug_map[id_b]['label']

            # A interagit avec B ?
            for inter in all_interactions.get(id_a, []):
                inter_dbid = inter.get('drugbank-id', '')
                if inter_dbid == id_b:
                    cross_interactions.append({
                        'drug_a': label_a,
                        'drug_a_id': id_a,
                        'drug_b': label_b,
                        'drug_b_id': id_b,
                        'description': inter.get('description', 'Interaction documentée sans description détaillée.'),
                        'source': 'DrugBank'
                    })
                    break
            else:
                # Vérifier dans l'autre sens (B interagit avec A)
                for inter in all_interactions.get(id_b, []):
                    inter_dbid = inter.get('drugbank-id', '')
                    if inter_dbid == id_a:
                        cross_interactions.append({
                            'drug_a': label_a,
                            'drug_a_id': id_a,
                            'drug_b': label_b,
                            'drug_b_id': id_b,
                            'description': inter.get('description', 'Interaction documentée sans description détaillée.'),
                            'source': 'DrugBank'
                        })
                        break

    # 4) Récupérer aussi les enzymes CYP partagées (interactions potentielles via métabolisme)
    enzyme_warnings = []
    drug_enzymes = {}
    for dbid in drug_map:
        chunks = list(db.drugbank_raw_chunks.find({
            'drugbank_id': dbid,
            'kind': 'enzymes'
        }))
        enzymes = set()
        for chunk in chunks:
            if chunk.get('data') and isinstance(chunk['data'], list):
                for enz in chunk['data']:
                    name = enz.get('name', '')
                    if name:
                        enzymes.add(name)
        drug_enzymes[dbid] = enzymes

    # Trouver les enzymes partagées
    for i in range(len(dbids)):
        for j in range(i + 1, len(dbids)):
            id_a = dbids[i]
            id_b = dbids[j]
            shared = drug_enzymes.get(id_a, set()) & drug_enzymes.get(id_b, set())
            if shared:
                enzyme_warnings.append({
                    'drug_a': drug_map[id_a]['label'],
                    'drug_b': drug_map[id_b]['label'],
                    'shared_enzymes': sorted(shared),
                    'warning': f"Ces deux médicaments sont métabolisés par les mêmes enzymes ({', '.join(sorted(shared))}), ce qui peut modifier leur efficacité ou leur toxicité."
                })

    # 5) Résumé
    result = {
        'drugs_analyzed': [
            {'label': info['label'], 'drugbank_id': dbid}
            for dbid, info in drug_map.items()
        ],
        'total_analyzed': len(drug_map),
        'interactions': cross_interactions,
        'interaction_count': len(cross_interactions),
        'enzyme_warnings': enzyme_warnings,
        'enzyme_warning_count': len(enzyme_warnings),
        'severity_summary': {
            'high': len(cross_interactions),  # Toute interaction DrugBank documentée = sérieuse
            'moderate': len(enzyme_warnings),  # Compétition enzymatique = modéré
        }
    }

    return jsonify(result)


@app.route('/set_language/<language>')
def set_language(language):
    """Route pour changer la langue de l'interface"""
    if language in app.config['LANGUAGES']:
        session['language'] = language
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    # La base est déjà initialisée plus haut avec init_db(app)
    # On s'assure juste que le système d'utilisateurs est prêt
    users.init_users(app)
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'])

# NOTE:
# La route d'admin /admin/database semble appartenir à un blueprint (users_bp)
# et devrait être définie dans un module de routes (par ex. users.py), pas ici.
# Pour éviter de casser l'application au démarrage, on la désactive ici.
#
# from flask import Blueprint
# from models import User as UserModel
#
# @users_bp.route('/admin/database')
# @role_required(UserModel.ROLE_ADMIN)
# def admin_database():
#     ...