# scrapers/models/medicine_market.py

from datetime import datetime

def build_medicine_market_doc(
    inn: str,
    brand_name: str,
    country: str,
    authority: str,
    laboratory: str | None = None,
    presentation: dict | None = None,
    documents: dict | None = None,
    source: dict | None = None,
):
    inn_normalized = inn.lower().strip()
    brand_norm = brand_name.lower().replace(" ", "_")

    return {
        "_id": f"market:{country.lower()}:{brand_norm}",
        "medicine_id": f"medicine:{inn_normalized}",

        "brand_name": brand_name,
        "laboratory": laboratory,

        "country": country,
        "authority": authority,

        # forme / dosage / voie
        "presentation": presentation or {},

        # RCP, monographie, PDF, HTML…
        "documents": documents or {},

        "source": source or {},

        "schema_version": 3,
        "created_at": int(datetime.utcnow().timestamp())
    }
