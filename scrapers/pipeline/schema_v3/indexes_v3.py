from scrapers.utils.mongo import get_collection

def ensure_indexes_v3():
    substances = get_collection("substances")
    medicines = get_collection("medicines")
    markets = get_collection("medicine_market")

    # substances
    substances.create_index([("inn", 1)], unique=True)
    substances.create_index([("identifiers.rxnorm_in", 1)])
    substances.create_index([("identifiers.atc", 1)])

    # medicines
    medicines.create_index([("main_inn", 1)], unique=True)
    medicines.create_index([("substance_ids", 1)])
    medicines.create_index([("rxnorm.ingredient", 1)])
    medicines.create_index([("atc", 1)])

    # medicine_market
    markets.create_index([("medicine_id", 1)])
    markets.create_index([("country", 1), ("brand_name", 1)])
    markets.create_index([("country", 1), ("presentation.form", 1), ("presentation.strength", 1)])
    markets.create_index([("regulatory.codes.cis", 1)], unique=True, sparse=True)
    markets.create_index([("documents.content_hash", 1)])
