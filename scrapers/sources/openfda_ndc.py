import os
import time
import random
import requests
import re
from typing import Any, Dict, List, Optional
from pymongo import UpdateOne

from scrapers.utils.mongo import get_collection


OPENFDA_NDC_URL = "https://api.fda.gov/drug/ndc.json"

def now_ts() -> int:
    return int(time.time())

def norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    # normalisation simple (tu peux durcir plus tard)
    return " ".join(str(s).strip().upper().split())

class OpenFdaClient:
    def __init__(self, api_key: Optional[str] = None, timeout_s: int = 30, max_retries: int = 6):
        self.session = requests.Session()
        self.api_key = api_key or os.getenv("OPENFDA_API_KEY")
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.api_key:
            params = dict(params)
            params["api_key"] = self.api_key

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout_s)
                if r.status_code == 404:
                    # OpenFDA renvoie parfois 404 si le search est invalide (ex: product_type inconnu)
                    return {"_skip_slice": True}
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"retryable status={r.status_code}", response=r)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                # backoff exponentiel + jitter
                sleep_s = min(30.0, (2 ** (attempt - 1)) * 0.5) + random.random() * 0.2
                time.sleep(sleep_s)

        raise last_err  # type: ignore


OPENFDA_SKIP_MAX = 25000  # limite pratique OpenFDA (au-delà -> 400)

def _count_total(client, search: str) -> int:
    """Retourne meta.results.total pour un search OpenFDA."""
    payload = client.get(OPENFDA_NDC_URL, params={"search": search, "limit": 1, "skip": 0})
    meta = (payload.get("meta") or {}).get("results") or {}
    return int(meta.get("total") or 0)

def _build_slices_ndc(base_search: str) -> List[str]:
    # product_type est supporté sur drug/ndc
    # (et ça répartit bien le volume)
    product_types = [
        "HUMAN PRESCRIPTION DRUG",
        "HUMAN OTC DRUG",
        "ANIMAL PRESCRIPTION DRUG",
        "ANIMAL OTC DRUG",
        "MEDICAL GAS",
        "BULK INGREDIENT",
        "HOMEOPATHIC",
    ]
    searches = []
    for pt in product_types:
        # guillemets obligatoires car espaces
        searches.append(f'{base_search} AND product_type:"{pt}"')
    return searches

def iter_ndc_records(
    client,
    *,
    limit_total: Optional[int] = None,
    page_size: int = 100,
    since_yyyymmdd: Optional[str] = None,
):
    base_search = "finished:true"
    # since_yyyymmdd: on ne l'applique pas ici car marketing_start_date cause 404 sur /drug/ndc
    # (on pourra faire un since plus tard avec un autre champ supporté)

    searches = _build_slices_ndc(base_search)

    yielded = 0
    for search in searches:
        skip = 0
        while True:
            params = {"search": search, "limit": page_size, "skip": skip}
            payload = client.get(OPENFDA_NDC_URL, params=params)
            if payload.get("_skip_slice"):
                print(f"[OPENFDA][NDC] SKIP invalid slice search={search}")
                break
            results = payload.get("results") or []
            if not results:
                break

            for rec in results:
                yield rec
                yielded += 1
                if limit_total and yielded >= limit_total:
                    return

            skip += page_size
            if skip > OPENFDA_SKIP_MAX:
                # si un product_type dépasse 25k, on devra le resharder (rare)
                break


def resolve_medicine_ref(
    meds_col,
    *,
    generic_name: Optional[str],
    brand_name: Optional[str],
) -> Optional[Any]:
    """
    Mapping déterministe (V3):
    - match exact sur medicines_v3.inns puis medicine_key (generic d'abord)
    - fallback brand uniquement si unique
    - fallback "head token" sur generic (ex: "LEUPROLIDE ACETATE" -> "LEUPROLIDE")
    """

    def clean_name(s: str) -> str:
        s = norm(s)  # doit renvoyer une string normalisée (upper/strip etc.)
        if not s:
            return ""
        # retire dosages (25 mg, 10mcg, etc.)
        s = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|units|u\.i\.)\b", "", s, flags=re.I)
        # retire ponctuation (garde lettres/chiffres/espace/tiret)
        s = re.sub(r"[^A-Z0-9\s\-]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    g = clean_name(generic_name or "")
    b = clean_name(brand_name or "")

    # 1) generic exact
    if g:
        doc = meds_col.find_one({"inns": g}, {"_id": 1})
        if doc:
            return doc["_id"]
        doc = meds_col.find_one({"medicine_key": g}, {"_id": 1})
        if doc:
            return doc["_id"]

    # 2) fallback "head token" sur generic
    if g and " " in g:
        head = g.split(" ", 1)[0]
        doc = meds_col.find_one({"inns": head}, {"_id": 1})
        if doc:
            return doc["_id"]
        doc = meds_col.find_one({"medicine_key": head}, {"_id": 1})
        if doc:
            return doc["_id"]

    # 3) fallback brand (uniquement si unique)
    if b:
        found = list(meds_col.find({"inns": b}, {"_id": 1}).limit(2))
        if len(found) == 1:
            return found[0]["_id"]

        found = list(meds_col.find({"medicine_key": b}, {"_id": 1}).limit(2))
        if len(found) == 1:
            return found[0]["_id"]

    return None

def ingest_openfda_ndc(
    *,
    limit: Optional[int] = None,
    since: Optional[str] = None,  # "YYYYMMDD"
    log_every: int = 500,
    dry_run: bool = False,
) -> Dict[str, Any]:
    market = get_collection("medicine_market")
    meds = get_collection("medicines_v3")



    client = OpenFdaClient()

    processed = upserts = modified = orphan = errors = 0
    bulk_ops: List[UpdateOne] = []

    def flush():
        nonlocal upserts, modified, bulk_ops
        if not bulk_ops:
            return
        if dry_run:
            bulk_ops = []
            return
        res = market.bulk_write(bulk_ops, ordered=False)
        upserts += (res.upserted_count or 0)
        modified += (res.modified_count or 0)
        bulk_ops = []

    for rec in iter_ndc_records(
        client,
        limit_total=limit,
        since_yyyymmdd=since,
    ):


        try:
            packaging_list = rec.get("packaging") or []
            if not packaging_list:
                continue

            brand = rec.get("brand_name")
            generic = rec.get("generic_name")

            for pack in packaging_list:
                pkg_ndc = pack.get("package_ndc")
                if not pkg_ndc:
                    continue

                _id = f"OPENFDA|US|{pkg_ndc}"

                # mapping simple (comme avant) : generic -> inns / medicine_key, fallback brand unique
                medicine_ref = resolve_medicine_ref(
                    meds_col=meds,
                    generic_name=generic,
                    brand_name=brand,
                )

                if medicine_ref is None:
                    orphan += 1

                update_set = {
                    "schema_version": 3,
                    "country": "US",
                    "brand_title": brand,
                    "updated_at": now_ts(),
                    "sources.openfda": {
                        "endpoint": "drug/ndc",
                        "package_ndc": pkg_ndc,
                        "product_ndc": rec.get("product_ndc"),
                        "brand_name": brand,
                        "generic_name": generic,
                        "manufacturer": rec.get("labeler_name"),
                        "labeler_name": rec.get("labeler_name"),
                        "dosage_form": rec.get("dosage_form"),
                        "route": rec.get("route"),
                        "product_type": rec.get("product_type"),
                        "marketing_category": rec.get("marketing_category"),
                        "application_number": rec.get("application_number"),
                        "openfda": rec.get("openfda"),
                        # pack-level
                        "package_description": pack.get("description"),
                        "package_marketing_start_date": pack.get("marketing_start_date"),
                        "package_sample": pack.get("sample"),
                        "ingested_at": now_ts(),
                    },
                }

                update_doc = {"$set": update_set, "$setOnInsert": {"created_at": now_ts()}}

                if medicine_ref is not None:
                    update_doc["$set"]["medicine_ref"] = medicine_ref

                bulk_ops.append(UpdateOne({"_id": _id}, update_doc, upsert=True))
                processed += 1

                if len(bulk_ops) >= 1000:
                    flush()

                if log_every and processed % log_every == 0:
                    print(f"[OPENFDA][NDC] processed={processed} upserts={upserts} modified={modified} orphan={orphan} errors={errors}")

        except Exception as e:
            errors += 1
            if log_every and errors % 50 == 0:
                print(f"[OPENFDA][NDC] errors={errors} last={e}")

    flush()

    out = {
        "processed": processed,
        "upserts": upserts,
        "modified": modified,
        "orphan": orphan,
        "errors": errors,
        "since": since,
        "dry_run": dry_run,
    }
    print(f"[OPENFDA][NDC] DONE: {out}")
    return out
