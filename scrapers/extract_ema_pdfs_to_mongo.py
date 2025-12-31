# scrapers/extract_ema_pdfs_to_mongo.py
from __future__ import annotations

import os
from datetime import datetime, timezone

from scrapers.utils.mongo import get_mongo_client  # <-- tu l'as déjà
from scrapers.utils.pdf_extract import extract_pdf


EMA_DIR = os.path.join("data", "pdfs", "ema")
DB_NAME = "test3"          # <- adapte si besoin
COLLECTION = "pdf_documents"
SOURCE = "ema"


def main():
    client = get_mongo_client()
    col = client[DB_NAME][COLLECTION]

    # Index utiles (idempotence + recherche)
    col.create_index([("sha256", 1)], unique=True)
    col.create_index([("source", 1), ("filename", 1)])

    pdf_files = [
        f for f in os.listdir(EMA_DIR)
        if f.lower().endswith(".pdf")
    ]

    print(f"{len(pdf_files)} PDF(s) trouvés dans {EMA_DIR}")

    for i, filename in enumerate(pdf_files, start=1):
        path = os.path.join(EMA_DIR, filename)

        try:
            data = extract_pdf(path)
        except Exception as e:
            print(f"[{i}/{len(pdf_files)}] ❌ extraction fail {filename}: {e}")
            col.update_one(
                {"source": SOURCE, "filename": filename},
                {"$set": {
                    "source": SOURCE,
                    "filename": filename,
                    "path": path,
                    "extraction_status": "error",
                    "error": str(e),
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            continue

        # Upsert by sha256 (évite doublons même si tu renommes)
        doc = {
            "source": SOURCE,
            "filename": filename,
            "path": path,
            "sha256": data.sha256,
            "num_pages": data.num_pages,
            "extraction_status": "ok",
            "extracted_at": datetime.now(timezone.utc),
            # RAW
            "text": data.text,
            # Structuré RCP (rubriques)
            "rcp_sections": data.rcp_sections,
        }

        col.update_one({"sha256": data.sha256}, {"$set": doc}, upsert=True)
        print(f"[{i}/{len(pdf_files)}] ✅ {filename} pages={data.num_pages} sections={len(data.rcp_sections)}")


if __name__ == "__main__":
    main()
