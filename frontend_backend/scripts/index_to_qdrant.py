from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from sentence_transformers import SentenceTransformer
import uuid

print("Connexion à MongoDB...")
mongo = MongoClient("mongodb://mongo:27017")
db = mongo["medicsearch"]
collection = db["medicines"]
print("Connexion à MongoDB réussie.")


print("Connexion à Qdrant...")
import time
import sys
from requests.exceptions import ConnectionError

# Tentative de connexion avec retry
max_retries = 5
retry_delay = 5

for attempt in range(max_retries):
    try:
        qdrant = QdrantClient(host="qdrant", port=6333, timeout=60, prefer_grpc=False)
        # Test la connexion
        qdrant.get_collections()
        print("Connexion à Qdrant réussie.")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            print(f"Tentative {attempt + 1} échouée. Nouvelle tentative dans {retry_delay} secondes...")
            time.sleep(retry_delay)
        else:
            print("Impossible de se connecter à Qdrant après plusieurs tentatives.")
            sys.exit(1)

print("Création ou recréation de la collection Qdrant...")
if qdrant.collection_exists("medicaments"):
    qdrant.delete_collection(collection_name="medicaments")

qdrant.create_collection(
    collection_name="medicaments",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
)
print("Collection Qdrant prête.")

print("Chargement du modèle d'embedding...")
model = SentenceTransformer("all-MiniLM-L6-v2")
print("Modèle chargé.")

print("Récupération des documents depuis MongoDB...")
docs = list(collection.find({}))
print(f"{len(docs)} documents récupérés.")

points = []
for i, doc in enumerate(docs, 1):
    title = doc.get("title", "") or ""
    details = doc.get("medicine_details", {}) or {}

    substances = " ".join(details.get("substances_actives", []) or [])
    forme = details.get("forme", "") or ""
    laboratoire = details.get("laboratoire", "") or ""

    # Sections RCP (tu les as déjà dans /medicine/<id> et /raw/<id>)
    sections_text_parts = []
    for section in doc.get("sections", []) or []:
        sec_title = section.get("title", "") or ""
        sections_text_parts.append(sec_title)
        for content_item in section.get("content", []) or []:
            if "text" in content_item and content_item["text"]:
                sections_text_parts.append(content_item["text"])

    sections_text = " ".join(sections_text_parts)

    indications = details.get("indications", "") or ""

    text = " ".join([
        title,
        substances,
        forme,
        indications,
        laboratoire,
        sections_text,
    ])

    mongo_id = doc["_id"]
    padded = mongo_id.binary + b'\x00' * 4
    point_id = str(uuid.UUID(bytes=padded))
    embedding = model.encode(text)

    points.append(PointStruct(
        id=point_id,
        vector=embedding.tolist(),
        payload={
            "title": title,
            "substances": details.get("substances_actives", []),
            "forme": forme,
            "laboratoire": laboratoire,
            "mongo_id": str(mongo_id),
        }
    ))

    if i % 100 == 0:
        print(f"{i} documents traités...")

BATCH_SIZE = 256
total = len(points)
print("Indexation dans Qdrant par lots...")
for i in range(0, total, BATCH_SIZE):
    batch = points[i:i+BATCH_SIZE]
    qdrant.upsert(collection_name="medicaments", points=batch)
    print(f"{min(i+BATCH_SIZE, total)}/{total} indexés...")

print(f"{total} médicaments indexés dans Qdrant.")
