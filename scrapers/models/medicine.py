# scrapers/models/medicine.py

from datetime import datetime

def build_medicine_doc(
    inn: str,
    forms: list[str] | None = None,
    strengths: list[str] | None = None,
):
    inn_normalized = inn.lower().strip()

    return {
        "_id": f"medicine:{inn_normalized}",
        "inn": inn,
        "substance_id": f"inn:{inn_normalized}",

        # formes & dosages globaux (union)
        "forms": forms or [],
        "strengths": strengths or [],

        # liens vers commercialisations
        "markets": [],

        "schema_version": 3,
        "created_at": int(datetime.utcnow().timestamp())
    }
