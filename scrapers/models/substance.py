# scrapers/models/substance.py

from datetime import datetime

def build_substance_doc(
    inn: str,
    atc_codes: list[str] | None = None,
    rxnorm: dict | None = None,
    sources: list[str] | None = None,
):
    inn_normalized = inn.lower().strip()

    return {
        "_id": f"inn:{inn_normalized}",
        "inn": inn,
        "inn_normalized": inn_normalized,

        "atc_codes": atc_codes or [],

        # RxNorm = optionnel
        "rxnorm": rxnorm or {
            "rxcui": None,
            "status": "not_checked"
        },

        "sources": sources or [],

        "schema_version": 3,
        "created_at": int(datetime.utcnow().timestamp())
    }
