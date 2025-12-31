# scrapers/migrate_ema_titles.py

from __future__ import annotations
import os

from scrapers.utils.mongo import get_collection
from scrapers.utils.pdf_extract import extract_pdf
from scrapers.utils.ema_title import extract_ema_title_from_sections, normalize_for_search


def main():
    col = get_collection("medicines")

    cursor = col.find(
        {
            "metadata.source": "ema",
            "$or": [{"title": None}, {"title": {"$exists": False}}],
            "metadata.pdf_path": {"$exists": True, "$type": "string"},
        },
        {"metadata.pdf_path": 1, "metadata.ema_id": 1}
    )

    updated = 0
    scanned = 0
    missing = 0

    for doc in cursor:
        pdf_path = doc.get("metadata", {}).get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            missing += 1
            continue

        extraction = extract_pdf(pdf_path)
        if not extraction.rcp_sections:
            scanned += 1
            continue

        title = extract_ema_title_from_sections(extraction.rcp_sections)
        if not title:
            continue

        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "title": title,
                "metadata.title_source": "ema_pdf_section_1",
                "metadata.search_title": normalize_for_search(title),
            }}
        )
        updated += 1

    print(f"✅ titles remplis: {updated}")
    print(f"⚠️ PDFs scannés/non exploitables: {scanned}")
    print(f"⚠️ PDF path manquants: {missing}")


if __name__ == "__main__":
    main()
