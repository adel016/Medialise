from scrapers.utils.mongo import get_collection

def _same_keys(existing_idx, keys):
    # existing_idx["key"] est un SON(dict) -> list(existing_idx["key"].items()) donne [("field", 1)]
    return list(existing_idx["key"].items()) == keys

def ensure_index(col, keys, *, name, unique=False, sparse=False):
    """
    - Skip si un index avec les mêmes keys existe déjà (même si nom différent)
    - Sinon crée avec name explicite
    """
    keys_list = list(keys)

    for idx in col.list_indexes():
        if _same_keys(idx, keys_list):
            # Si un index existe déjà sur ces keys, on ne touche pas (même s'il a un autre nom)
            print(f"[INDEX] exists-by-keys: {col.name} keys={keys_list} (name={idx['name']})")
            return

    col.create_index(keys_list, name=name, unique=unique, sparse=sparse)
    print(f"[INDEX] created: {col.name}.{name}")

def main():
    market = get_collection("medicine_market")
    meds = get_collection("medicines")
    subs = get_collection("substances")

    ensure_index(market, [("sources.openfda.package_ndc", 1)], name="openfda_package_ndc_1", unique=True, sparse=True)
    ensure_index(market, [("sources.openfda.product_ndc", 1)], name="openfda_product_ndc_1", sparse=True)
    ensure_index(market, [("country", 1)], name="country_1")
    ensure_index(market, [("medicine_ref", 1)], name="medicine_ref_1")

    ensure_index(meds, [("sources.openfda.generic_names", 1)], name="openfda_generic_names_1", sparse=True)
    ensure_index(meds, [("sources.openfda.brand_names", 1)], name="openfda_brand_names_1", sparse=True)

    # label_normalized: on ne force pas unique ici (tu as déjà un index)
    ensure_index(subs, [("label_normalized", 1)], name="label_normalized_1")

    print("[OPENFDA][INDEX] OK")

if __name__ == "__main__":
    main()
