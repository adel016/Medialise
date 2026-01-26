# scrapers/sources/drugbank.py
from __future__ import annotations

import io
import os
import time
import zipfile
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection


# =========================================================
# Helpers
# =========================================================

def _now_ts() -> int:
    return int(time.time())


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t if t else None


def _norm_label(s: str) -> str:
    return s.strip().upper()


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def _get_db(mongo_uri: str, mongo_db: str) -> Database:
    client = MongoClient(mongo_uri)
    return client[mongo_db]


# =========================================================
# Open XML (.xml or .zip containing .xml) without extracting
# =========================================================

def _open_xml_from_zip(zip_path: str) -> io.BufferedReader:
    zf = zipfile.ZipFile(zip_path, "r")
    xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
    if not xml_names:
        zf.close()
        raise FileNotFoundError(f"No .xml inside zip: {zip_path}")

    xml_name = sorted(xml_names)[0]
    raw = zf.open(xml_name, "r")
    buf = io.BufferedReader(raw)

    # Keep references alive
    buf._drugbank_zipfile = zf  # type: ignore[attr-defined]
    buf._drugbank_zipraw = raw  # type: ignore[attr-defined]
    return buf


def open_drugbank_xml(path: str):
    p = path.lower()
    if p.endswith(".zip"):
        return _open_xml_from_zip(path)
    return open(path, "rb")


# =========================================================
# Mongo Indexes
# =========================================================

def ensure_indexes(db: Database) -> None:
    db["substances_v3"].create_index("label_normalized")
    db["substances_v3"].create_index("sources.drugbank.drugbank_id")
    db["substances_v3"].create_index("sources.drugbank.inchi_key")
    db["substances_v3"].create_index("sources.drugbank.cas")
    db["substances_v3"].create_index("sources.drugbank.unii")
    db["substances_v3"].create_index("sources.pubchem.summary.inchi_key")
    db["substances_v3"].create_index("sources.pubchem.synonyms_top")

    db["medicines_v3"].create_index("medicine_key")
    db["medicines_v3"].create_index("inns")
    db["medicines_v3"].create_index("sources.drugbank.drugbank_id")

    db["medicine_market"].create_index("sources.drugbank.product_key")

    db["drugbank_raw_chunks"].create_index(
        [("drugbank_id", 1), ("kind", 1), ("seq", 1)],
        unique=True,
        sparse=True,
    )


# =========================================================
# XML parsing helpers (namespace-agnostic)
# =========================================================

def _find_child(el: ET.Element, tag: str) -> Optional[ET.Element]:
    for c in el:
        if _strip_ns(c.tag) == tag:
            return c
    return None


def _find_children(el: ET.Element, tag: str) -> List[ET.Element]:
    out = []
    for c in el:
        if _strip_ns(c.tag) == tag:
            out.append(c)
    return out


def _extract_drugbank_ids(drug_el: ET.Element) -> Tuple[Optional[str], List[str]]:
    ids_el = _find_children(drug_el, "drugbank-id")
    primary = None
    all_ids: List[str] = []
    for ide in ids_el:
        val = _text(ide)
        if not val:
            continue
        all_ids.append(val)
        if ide.attrib.get("primary", "").lower() == "true":
            primary = val
    if primary is None and all_ids:
        primary = all_ids[0]
    return primary, all_ids


def _extract_synonyms(drug_el: ET.Element, max_syn: int = 300) -> List[str]:
    syns_el = _find_child(drug_el, "synonyms")
    if syns_el is None:
        return []
    out: List[str] = []
    seen = set()
    for s in _find_children(syns_el, "synonym"):
        t = _text(s)
        if not t:
            continue
        k = _norm_label(t)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
        if len(out) >= max_syn:
            break
    return out


def _extract_atc_codes(drug_el: ET.Element) -> List[str]:
    atc_el = _find_child(drug_el, "atc-codes")
    if atc_el is None:
        return []
    out: List[str] = []
    for c in _find_children(atc_el, "atc-code"):
        code = c.attrib.get("code")
        if code:
            out.append(code.strip())
    return list(dict.fromkeys(out))


def _extract_calculated_props(drug_el: ET.Element) -> Dict[str, Optional[str]]:
    props = {"inchi_key": None, "inchi": None, "smiles": None}
    cp = _find_child(drug_el, "calculated-properties")
    if cp is None:
        return props

    for prop in _find_children(cp, "property"):
        kind = _text(_find_child(prop, "kind"))
        val = _text(_find_child(prop, "value"))
        if not kind or not val:
            continue
        k = kind.strip().casefold()
        if k == "inchikey":
            props["inchi_key"] = val
        elif k == "inchi":
            props["inchi"] = val
        elif k in ("smiles", "canonical smiles"):
            props["smiles"] = val
    return props


def _extract_external_ids(drug_el: ET.Element) -> Dict[str, Optional[str]]:
    out = {"cas": None, "unii": None}
    ext = _find_child(drug_el, "external-identifiers")
    if ext is None:
        return out

    for ex in _find_children(ext, "external-identifier"):
        res = _text(_find_child(ex, "resource"))
        ident = _text(_find_child(ex, "identifier"))
        if not res or not ident:
            continue
        r = res.strip().casefold()
        if r == "cas":
            out["cas"] = ident
        elif r == "unii":
            out["unii"] = ident
    return out


def _extract_products(drug_el: ET.Element, max_products: int = 800) -> List[Dict[str, Any]]:
    prods = _find_child(drug_el, "products")
    if prods is None:
        return []
    out: List[Dict[str, Any]] = []
    for p in _find_children(prods, "product"):
        name = _text(_find_child(p, "name"))
        country = _text(_find_child(p, "country"))
        labeller = _text(_find_child(p, "labeller"))
        ndc = _text(_find_child(p, "ndc-id"))
        if not any([name, country, labeller, ndc]):
            continue
        out.append({"name": name, "country": country, "labeller": labeller, "ndc_id": ndc})
        if len(out) >= max_products:
            break
    return out


# =========================================================
# 16MB-safe: store big blocks separately (raw chunks)
# =========================================================

def _safe_store_raw_chunks(
    raw_col: Collection,
    drugbank_id: str,
    kind: str,
    payload: Any,
    max_chunk_bytes: int = 12_000_000,
) -> int:
    now = _now_ts()

    if isinstance(payload, list):
        chunks: List[List[Any]] = []
        cur: List[Any] = []
        cur_size = 0

        for item in payload:
            est = len(str(item).encode("utf-8", errors="ignore")) + 200
            if cur and (cur_size + est) > max_chunk_bytes:
                chunks.append(cur)
                cur = []
                cur_size = 0
            cur.append(item)
            cur_size += est

        if cur:
            chunks.append(cur)

        for i, part in enumerate(chunks):
            raw_col.update_one(
                {"drugbank_id": drugbank_id, "kind": kind, "seq": i},
                {"$set": {"drugbank_id": drugbank_id, "kind": kind, "seq": i, "data": part, "updated_at": now}},
                upsert=True,
            )
        return len(chunks)

    raw_col.update_one(
        {"drugbank_id": drugbank_id, "kind": kind, "seq": 0},
        {"$set": {"drugbank_id": drugbank_id, "kind": kind, "seq": 0, "data": payload, "updated_at": now}},
        upsert=True,
    )
    return 1


# =========================================================
# Matching strategy (Priority A)
# =========================================================

def _find_substance_match(
    subs_col: Collection,
    inchi_key: Optional[str],
    cas: Optional[str],
    unii: Optional[str],
    label: str,
    synonyms: List[str],
) -> Optional[Dict[str, Any]]:
    if inchi_key:
        doc = subs_col.find_one(
            {"$or": [{"sources.drugbank.inchi_key": inchi_key}, {"sources.pubchem.summary.inchi_key": inchi_key}]},
            {"_id": 1},
        )
        if doc:
            return doc

    if cas:
        doc = subs_col.find_one(
            {"$or": [{"sources.drugbank.cas": cas}, {"sources.pubchem.synonyms_top": cas}]},
            {"_id": 1},
        )
        if doc:
            return doc

    if unii:
        doc = subs_col.find_one(
            {"$or": [{"sources.drugbank.unii": unii}, {"sources.pubchem.synonyms_top": f"UNII-{unii}"}]},
            {"_id": 1},
        )
        if doc:
            return doc

    norms = list(dict.fromkeys([_norm_label(x) for x in ([label] + synonyms[:50]) if x]))
    if norms:
        doc = subs_col.find_one({"label_normalized": {"$in": norms}}, {"_id": 1})
        if doc:
            return doc

    return None


# =========================================================
# Upserts to YOUR V3 schema
# =========================================================

def _upsert_substance_v3(
    subs_col: Collection,
    raw_col: Collection,
    *,
    drugbank_id: str,
    label: str,
    atc_codes: List[str],
    inchi_key: Optional[str],
    inchi: Optional[str],
    smiles: Optional[str],
    cas: Optional[str],
    unii: Optional[str],
    synonyms: List[str],
    store_raw_chunks: bool,
    raw_blocks: Optional[Dict[str, Any]] = None,
) -> Any:
    now = _now_ts()

    match = _find_substance_match(
        subs_col=subs_col,
        inchi_key=inchi_key,
        cas=cas,
        unii=unii,
        label=label,
        synonyms=synonyms,
    )

    drugbank_block = {
        "drugbank_id": drugbank_id,
        "label": label,
        "atc_codes": atc_codes,
        "inchi_key": inchi_key,
        "inchi": inchi,
        "smiles": smiles,
        "cas": cas,
        "unii": unii,
        "synonyms": synonyms[:300],
        "ingested_at": now,
    }

    set_doc = {
        "updated_at": now,
        "label": label,
        "label_normalized": _norm_label(label),
        "sources.drugbank.drugbank_id": drugbank_id,
        "sources.drugbank.label": label,
        "sources.drugbank.atc_codes": atc_codes,
        "sources.drugbank.inchi_key": inchi_key,
        "sources.drugbank.inchi": inchi,
        "sources.drugbank.smiles": smiles,
        "sources.drugbank.cas": cas,
        "sources.drugbank.unii": unii,
        "sources.drugbank.synonyms": synonyms[:300],
        "sources.drugbank.ingested_at": now,
    }
    set_on_insert = {
        "created_at": now,
        "legacy": {"substances_id": label},
    }

    if match:
        subs_col.update_one(
            {"_id": match["_id"]},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        sid = match["_id"]
    else:
        res = subs_col.update_one(
            {"sources.drugbank.drugbank_id": drugbank_id},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        if res.upserted_id is not None:
            sid = res.upserted_id
        else:
            doc = subs_col.find_one({"sources.drugbank.drugbank_id": drugbank_id}, {"_id": 1})
            sid = doc["_id"] if doc else None

    if store_raw_chunks and raw_blocks:
        for kind, payload in raw_blocks.items():
            _safe_store_raw_chunks(raw_col, drugbank_id=drugbank_id, kind=kind, payload=payload)

    return sid


def _find_or_create_medicine_v3(
    meds_col: Collection,
    *,
    drugbank_id: str,
    drug_name: str,
    substance_ref_id: Any,
) -> Any:
    now = _now_ts()

    doc = meds_col.find_one(
        {"$or": [{"medicine_key": drug_name}, {"inns": drug_name}, {"sources.drugbank.drugbank_id": drugbank_id}]},
        {"_id": 1},
    )

    if doc:
        meds_col.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "updated_at": now,
                    "sources.drugbank": {"drugbank_id": drugbank_id, "name": drug_name, "ingested_at": now},
                },
                "$addToSet": {"substance_ref_ids": substance_ref_id, "inns": drug_name},
            },
        )
        return doc["_id"]

    res = meds_col.insert_one(
        {
            "schema_version": 3,
            "created_at": now,
            "updated_at": now,
            "countries": [],
            "inns": [drug_name],
            "substance_ids": [],
            "substance_labels": [],
            "substance_ref_ids": [substance_ref_id] if substance_ref_id is not None else [],
            "legacy": {"medicine_id": drug_name},
            "medicine_key": drug_name,
            "sources": {"drugbank": {"drugbank_id": drugbank_id, "name": drug_name, "ingested_at": now}},
        }
    )
    return res.inserted_id


def _upsert_market_products_v3(
    market_col: Collection,
    *,
    medicine_ref: Any,
    drugbank_id: str,
    products: List[Dict[str, Any]],
) -> int:
    now = _now_ts()
    n = 0

    for p in products:
        country = (p.get("country") or "INT").strip() or "INT"
        brand = (p.get("name") or "").strip() or None
        labeller = (p.get("labeller") or "").strip() or None
        ndc = (p.get("ndc_id") or "").strip() or None

        key_src = "|".join([drugbank_id, country, brand or "", labeller or "", ndc or ""])
        product_key = _sha1(key_src)

        market_id = f"DB|{country}|{product_key}"

        res = market_col.update_one(
            {"_id": market_id},
            {
                "$setOnInsert": {"created_at": now},
                "$set": {
                    "updated_at": now,
                    "schema_version": 3,
                    "medicine_ref": medicine_ref,
                    "country": country,
                    "brand_title": brand,
                    "laboratory": labeller,
                    "sources.drugbank.drugbank_id": drugbank_id,
                    "sources.drugbank.product_key": product_key,
                    "sources.drugbank.ndc_id": ndc,
                    "sources.drugbank.ingested_at": now,
                    "kind": "drugbank_market",
                },
            },
            upsert=True,
        )
        # count only real writes
        if res.upserted_id is not None or res.modified_count > 0:
            n += 1



    return n


# =========================================================
# Optional heavy blocks -> raw chunks
# =========================================================

def _extract_raw_big_blocks(drug_el: ET.Element) -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    for tag in ("targets", "enzymes", "transporters", "carriers", "pathways", "drug-interactions"):
        child = _find_child(drug_el, tag)
        if child is None:
            continue

        items: List[Dict[str, Any]] = []
        for item in list(child):
            d: Dict[str, Any] = {}
            for sub in list(item):
                key = _strip_ns(sub.tag)
                val = _text(sub)
                if val:
                    d[key] = val
            if d:
                items.append(d)

        if items:
            raw[tag] = items

    return raw


# =========================================================
# Main ingest
# =========================================================

def ingest_drugbank(
    *,
    xml_or_zip_path: str,
    mongo_uri: str,
    mongo_db: str,
    limit: Optional[int] = None,
    log_every: int = 100,
    store_raw_chunks: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if not os.path.exists(xml_or_zip_path):
        raise FileNotFoundError(xml_or_zip_path)

    db = _get_db(mongo_uri, mongo_db)
    ensure_indexes(db)

    subs_col = db["substances_v3"]
    meds_col = db["medicines_v3"]
    market_col = db["medicine_market"]
    raw_col = db["drugbank_raw_chunks"]
    meta_col = db["metadata"]

    run_id = f"drugbank_ingest_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    started = _now_ts()

    if not dry_run:
        meta_col.update_one(
            {"_id": run_id},
            {"$set": {"_id": run_id, "type": "drugbank_ingest", "path": xml_or_zip_path, "started_at": started, "status": "running"}},
            upsert=True,
        )

    f = open_drugbank_xml(xml_or_zip_path)

    processed = 0
    market_upserts = 0
    errors_count = 0

    context = ET.iterparse(f, events=("end",))
    for _, elem in context:
        if _strip_ns(elem.tag) != "drug":
            continue

        try:
            drugbank_id, _all_ids = _extract_drugbank_ids(elem)
            if not drugbank_id:
                elem.clear()
                continue

            name = _text(_find_child(elem, "name")) or drugbank_id
            synonyms = _extract_synonyms(elem)
            atc_codes = _extract_atc_codes(elem)
            props = _extract_calculated_props(elem)
            ext = _extract_external_ids(elem)
            products = _extract_products(elem)

            raw_blocks = _extract_raw_big_blocks(elem) if store_raw_chunks else {}

            if not dry_run:
                sid = _upsert_substance_v3(
                    subs_col=subs_col,
                    raw_col=raw_col,
                    drugbank_id=drugbank_id,
                    label=name,
                    atc_codes=atc_codes,
                    inchi_key=props.get("inchi_key"),
                    inchi=props.get("inchi"),
                    smiles=props.get("smiles"),
                    cas=ext.get("cas"),
                    unii=ext.get("unii"),
                    synonyms=synonyms,
                    store_raw_chunks=store_raw_chunks,
                    raw_blocks=raw_blocks,
                )

                mid = _find_or_create_medicine_v3(
                    meds_col=meds_col,
                    drugbank_id=drugbank_id,
                    drug_name=name,
                    substance_ref_id=sid,
                )

                if products:
                    market_upserts += _upsert_market_products_v3(
                        market_col=market_col,
                        medicine_ref=mid,
                        drugbank_id=drugbank_id,
                        products=products,
                    )

            processed += 1
            if processed % log_every == 0:
                print(f"[DrugBank] processed={processed} market_upserts={market_upserts}")

            elem.clear()

            if limit is not None and processed >= limit:
                break

        except Exception as e:
            errors_count += 1
            print(f"[DrugBank] ERROR: {type(e).__name__}: {e}")
            elem.clear()

    finished = _now_ts()

    if not dry_run:
        meta_col.update_one(
            {"_id": run_id},
            {"$set": {"finished_at": finished, "status": "done", "processed": processed, "market_upserts": market_upserts, "errors_count": errors_count}},
            upsert=True,
        )

    return {"run_id": run_id, "processed": processed, "market_upserts": market_upserts, "errors_count": errors_count}


# =========================================================
# CLI (optional direct run)
# =========================================================

def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description="DrugBank ingest for MEDIALISE V3 (label/label_normalized)")
    p.add_argument("--path", required=True, help="Path to DrugBank XML or XML.ZIP")
    p.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    p.add_argument("--mongo-db", default=os.getenv("MONGO_DB", "medicsearch"))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--log-every", type=int, default=100)
    p.add_argument("--no-raw-chunks", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    out = ingest_drugbank(
        xml_or_zip_path=args.path,
        mongo_uri=args.mongo_uri,
        mongo_db=args.mongo_db,
        limit=args.limit,
        log_every=args.log_every,
        store_raw_chunks=not args.no_raw_chunks,
        dry_run=args.dry_run,
    )
    print(out)
