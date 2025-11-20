from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

qdrant = QdrantClient(host="qdrant", port=6333)
model = SentenceTransformer("all-MiniLM-L6-v2")

# Exemple de requête utilisateur
query = "antibiotique infection urinaire"
query_vector = model.encode(query).tolist()

# Recherche vectorielle dans Qdrant
results = qdrant.query_points(
    collection_name="medicaments",
    query_vector=query_vector,  # <-- correction ici
    limit=5
).result

print("Résultats de la recherche vectorielle :")
for res in results:
    print(f"Score: {res.score:.3f} | ID: {res.id} | Titre: {res.payload.get('title', '')}")
