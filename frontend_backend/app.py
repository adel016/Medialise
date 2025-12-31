from ai_summary import get_or_generate_summary, call_mistral_reformulate, call_mistral_summarize
# --- Initialisation Flask et Qdrant ---

from flask import Flask, request, render_template, jsonify, abort, redirect, url_for, stream_with_context, Response, session, g
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

# --- Initialisation Flask et Qdrant ---
app = Flask(__name__)
# Charger la configuration

app_config = get_config()
app.config.from_object(app_config)

qdrant_client = QdrantClient("qdrant", port=6333)
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

def wait_for_mongo(uri, timeout=30):
    """Attend que Mongo soit joignable avant de continuer."""
    start = time.time()
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    while True:
        try:
            client.admin.command("ping")
            print("MongoDB est prêt.")
            return
        except ServerSelectionTimeoutError:
            if time.time() - start > timeout:
                raise
            print("MongoDB pas encore prêt, nouvelle tentative...")
            time.sleep(2)

@app.route('/vector-search', methods=['GET', 'POST'])
def vector_search():
    """Recherche vectorielle sémantique via Qdrant avec pagination et affichage enrichi"""
    results = []
    query = request.args.get('query', '').strip()
    initial_count = 10
    load_more_count = 10
    total = 0

    if query:
        # 1) Embedding de la requête
        query_vector = embedding_model.encode(query).tolist()

        # 2) Appel à Qdrant avec query_points -> QueryResponse.points
        qdrant_response = qdrant_client.query_points(
            collection_name="medicaments",
            query=query_vector,
            limit=1000
        )
        qdrant_results = qdrant_response.points or []

        # 3) Filtrer par score minimum (seuil raisonnable)
        filtered_qdrant = [
            res for res in qdrant_results
            if getattr(res, "score", None) is not None and res.score >= 0.05
        ]
        total = len(filtered_qdrant)

        # 4) Récupérer les documents Mongo associés
        for res in filtered_qdrant:
            payload = getattr(res, "payload", {}) or {}
            mongo_id = payload.get("mongo_id")
            med = None
            if mongo_id:
                med = collection.find_one({'_id': ObjectId(mongo_id)})
                if med and '_id' in med:
                    med['_id'] = str(med['_id'])

            results.append({
                'score': getattr(res, 'score', None),
                'title': payload.get('title', ''),
                'mongo_id': str(mongo_id) if mongo_id else '',
                'medicine': med
            })

    return render_template(
        "vector_search.html",
        results=results,
        query=query,
        total=total,
        initial_count=initial_count,
        load_more_count=load_more_count,
    )


# Attendre Mongo AVANT init_db
wait_for_mongo(app.config["MONGO_URI"])

# Important: Initialiser la base de données avant d'accéder à mongo.db
init_db(app)

# Utiliser mongo.db pour accéder à la base de données MongoDB après l'initialisation
# Utiliser la bonne collection MongoDB : 'medicines'
db = mongo.db
collection = db['medicines']
# Définir db comme attribut de l'application pour qu'il soit accessible partout
app.db = db

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
    """Page d'accueil"""
    # Utiliser la connexion MongoDB déjà établie au lieu de models.mongo.db
    
    # Obtenir des statistiques sur la base de données
    total_medicines = collection.count_documents({})
    
    # Récupérer des statistiques de base
    lab_count = len(db.medicines.distinct("medicine_details.laboratoire"))
    substance_count = len(db.medicines.distinct("medicine_details.substances_actives"))
    
    # Récupérer les médicaments les plus récemment mis à jour pour la section "featured"
    featured_medicines = list(db.medicines.find({}, {"title": 1, "update_date": 1})
                           .sort("update_date", -1).limit(3))
    
    return render_template('index.html',
                          total_medicines=total_medicines,
                          lab_count=lab_count,
                          substance_count=substance_count,
                          featured_medicines=featured_medicines)

def extract_filter_options():
    """Extrait les options de filtre disponibles à partir de l'ensemble de la base de données"""
    # Vérifier si nous avons déjà extrait les options de filtrage
    cached_filters = getattr(extract_filter_options, 'cached_filters', None)
    if cached_filters:
        return cached_filters
    
    # Initialiser les ensembles pour stocker les valeurs uniques
    substances_actives = set()
    formes_pharma = set()
    laboratoires = set()
    dosages = set()
    
    # Analyser un échantillon représentatif de la base de données
    try:
        sample_size = 100
        medicines = list(collection.find().limit(sample_size))
        
        for medicine in medicines:
            # Extraction directement depuis medicine_details
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
    except Exception as e:
        print(f"Erreur lors de l'extraction des filtres: {e}")
    
    # Convertir en listes triées
    result = {
        'substances': sorted(list(substances_actives)),
        'formes': sorted(list(formes_pharma)),
        'laboratoires': sorted(list(laboratoires)),
        'dosages': sorted(list(dosages))
    }
    
    # Cacher les résultats comme attribut de la fonction pour les prochains appels
    extract_filter_options.cached_filters = result
    return result

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
    sort_option = request.args.get('sort', 'date_desc')
    advanced_search = substance or forme or laboratoire or dosage or sort_option != 'date_desc'
    
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
            comments=comments
        )

    except Exception as e:
        print(f"Erreur dans medicine_details: {e}")
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

@app.route('/api/search-results')
def search_results_api():
    try:
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

        # Calculer le nombre de documents correspondant à la requête
        total_results = collection.count_documents(query)

        # Gestion du tri
        if sort_option == 'relevance' and search_query:
            # Calculer le score de pertinence pour chaque médicament
            medicines = list(collection.find(query).skip((page - 1) * per_page).limit(per_page))
            for medicine in medicines:
                medicine['relevance_score'] = calculate_relevance_score(medicine, search_query)
            # Trier les médicaments par score de pertinence
            medicines = sorted(medicines, key=lambda x: x['relevance_score'], reverse=True)
        elif sort_option.startswith('name'):
            # Tri par nom
            sort_field = 'title'
            sort_direction = 1 if sort_option == 'name_asc' else -1
            medicines = list(collection.find(query).sort([(sort_field, sort_direction)]).skip((page - 1) * per_page).limit(per_page))
        else:
            # Tri par date (par défaut)
            sort_direction = -1 if sort_option == 'date_desc' else 1
            medicines = list(collection.find(query).skip((page - 1) * per_page).limit(per_page))
            medicines = sort_medicines_by_date(medicines, sort_direction)

        # Préparer les résultats formatés
        formatted_results = []
        for medicine in medicines:
            # Calculer le score de pertinence si la recherche est effectuée
            if search_query:
                relevance_score = calculate_relevance_score(medicine, search_query)
                medicine['search_matches'] = find_search_term_locations(medicine, search_query)
            else:
                relevance_score = 0
                medicine['search_matches'] = []
            formatted_results.append({
                'id': str(medicine['_id']),
                'title': get_display_title(medicine),
                'update_date': get_update_date(medicine),

                # garder les 2 pour le front (compat)
                'drug': medicine.get('drug', {}),
                'medicine_details': medicine.get('medicine_details', {}),

                'relevance_score': relevance_score,
                'match_count': medicine.get('match_count', 0),
                'search_matches': medicine.get('search_matches', [])
            })


        # Calculer s'il y a plus de résultats
        has_more = (page * per_page) < total_results

        return jsonify({
            'results': formatted_results,
            'has_more': has_more,
            'total_results': total_results,
            'total_pages': (total_results + per_page - 1) // per_page
        })
    except Exception as e:
        import traceback
        print("[API ERROR /api/search-results]", e)
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

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

@app.route('/api/medicine-summary/<id>')
def get_medicine_summary(id):
    """API endpoint to get the AI summary of a medicine"""
    try:
        # First check if we already have the summary in the database
        stored_medicine = db.medicines.find_one(
            {'_id': ObjectId(id)},
            {'ai_summary': 1}
        )
        
        if stored_medicine and 'ai_summary' in stored_medicine and stored_medicine['ai_summary']:
            return jsonify({
                "success": True,
                "summary": stored_medicine['ai_summary']
            })
        
        # If not, generate a new summary
        medicine = collection.find_one({'_id': ObjectId(id)})
        if not medicine:
            return jsonify({"success": False, "message": "Médicament non trouvé"}), 404
        
        # Generate summary but don't wait for it in the page load
        summary = get_or_generate_summary(medicine, db=db)
        
        # Return the generated summary
        return jsonify({
            "success": True,
            "summary": summary
        })
    except Exception as e:
        print(f"Error retrieving medicine summary: {e}")
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