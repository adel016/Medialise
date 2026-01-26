import os
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from neo4j import GraphDatabase


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "medicsearch")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:17687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "CHANGE_ME")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

BATCH_SIZE = int(os.getenv("NEO4J_BATCH_SIZE", "500"))


def oid_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    try:
        return str(x)
    except Exception:
        return None


def chunked(it: Iterable[Dict[str, Any]], size: int):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def pick_sources_tags(doc: Dict[str, Any]) -> List[str]:
    sources = doc.get("sources", {})
    if isinstance(sources, dict):
        return sorted([k for k, v in sources.items() if v is not None])
    return []


def extract_substance_ref_ids(mdoc: Dict[str, Any]) -> List[str]:
    # Verrouillé sur ta structure réelle
    sids: List[str] = []
    val = mdoc.get("substance_ref_ids")
    if isinstance(val, list):
        for it in val:
            s = oid_str(it)
            if s:
                sids.append(s)
    return sorted(list(set(sids)))


CYPHER_MERGE_MEDICINES = """
UNWIND $rows AS row
MERGE (m:Medicine {mongo_id: row.mongo_id})
SET
  m.medicine_key = coalesce(row.medicine_key, m.medicine_key),
  m.inns = coalesce(row.inns, m.inns),
  m.countries = coalesce(row.countries, m.countries),
  m.schema_version = coalesce(row.schema_version, m.schema_version)
"""

CYPHER_MERGE_SUBSTANCES = """
UNWIND $rows AS row
MERGE (s:Substance {label_normalized: row.label_normalized})
SET s.label = coalesce(row.label, s.label)
SET s.mongo_id = coalesce(s.mongo_id, row.mongo_id)
"""


CYPHER_MERGE_MARKETPRODUCTS = """
UNWIND $rows AS row
MERGE (p:MarketProduct {mp_id: row.mp_id})
SET
  p.country = coalesce(row.country, p.country),
  p.brand_title = coalesce(row.brand_title, p.brand_title),
  p.form = coalesce(row.form, p.form),
  p.strength = coalesce(row.strength, p.strength),
  p.laboratory = coalesce(row.laboratory, p.laboratory),
  p.cis = coalesce(row.cis, p.cis),
  p.source_tags = coalesce(row.source_tags, p.source_tags),
  p.schema_version = coalesce(row.schema_version, p.schema_version)
"""

CYPHER_LINK_MP_TO_MEDICINE = """
UNWIND $rows AS row
MATCH (p:MarketProduct {mp_id: row.mp_id})
MATCH (m:Medicine {mongo_id: row.medicine_mongo_id})
MERGE (p)-[r:REFERS_TO]->(m)
SET r.via = "medicine_ref"
"""

CYPHER_LINK_MED_TO_SUB = """
UNWIND $rows AS row
MATCH (m:Medicine {mongo_id: row.medicine_mongo_id})
MATCH (s:Substance {mongo_id: row.substance_mongo_id})
MERGE (m)-[:HAS_SUBSTANCE]->(s)
"""


def main():
    mongo = MongoClient(MONGO_URI)[MONGO_DB]
    col_m = mongo["medicines_v3"]
    col_s = mongo["substances_v3"]
    col_mp = mongo["medicine_market"]

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # 1) Medicines
    print("[1/5] Loading Medicine nodes...")
    cur = col_m.find({}, {"_id": 1, "medicine_key": 1, "inns": 1, "countries": 1, "schema_version": 1})
    rows = (
        {
            "mongo_id": oid_str(d["_id"]),
            "medicine_key": d.get("medicine_key"),
            "inns": d.get("inns"),
            "countries": d.get("countries"),
            "schema_version": d.get("schema_version"),
        }
        for d in cur
    )
    with driver.session(database=NEO4J_DATABASE) as session:
        for batch in chunked(rows, BATCH_SIZE):
            session.run(CYPHER_MERGE_MEDICINES, rows=batch)
    print("  OK")

    # 2) Substances
    print("[2/5] Loading Substance nodes...")
    cur = col_s.find({}, {"_id": 1, "label_normalized": 1, "label": 1})

    def subst_rows():
        for d in cur:
            label_norm = d.get("label_normalized")
            if not label_norm:
                continue  # sécurité
            yield {
                "label_normalized": label_norm,
                "label": d.get("label"),
                "mongo_id": oid_str(d["_id"]),
            }

    with driver.session(database=NEO4J_DATABASE) as session:
        for batch in chunked(subst_rows(), BATCH_SIZE):
            session.run(CYPHER_MERGE_SUBSTANCES, rows=batch)
    print("  OK")

    # 3) MarketProducts
    print("[3/5] Loading MarketProduct nodes...")
    cur = col_mp.find({}, {"_id": 1, "country": 1, "brand_title": 1, "form": 1, "strength": 1, "laboratory": 1, "cis": 1, "sources": 1, "schema_version": 1})
    rows = (
        {
            "mp_id": str(d["_id"]),
            "country": d.get("country"),
            "brand_title": d.get("brand_title"),
            "form": d.get("form"),
            "strength": d.get("strength"),
            "laboratory": d.get("laboratory"),
            "cis": d.get("cis"),
            "source_tags": pick_sources_tags(d),
            "schema_version": d.get("schema_version"),
        }
        for d in cur
    )
    with driver.session(database=NEO4J_DATABASE) as session:
        for batch in chunked(rows, BATCH_SIZE):
            session.run(CYPHER_MERGE_MARKETPRODUCTS, rows=batch)
    print("  OK")

    # 4) Link MarketProduct -> Medicine
    print("[4/5] Linking MarketProduct -> Medicine...")
    cur = col_mp.find({"medicine_ref": {"$exists": True, "$ne": None}}, {"_id": 1, "medicine_ref": 1})
    rows = (
        {"mp_id": str(d["_id"]), "medicine_mongo_id": oid_str(d.get("medicine_ref"))}
        for d in cur
        if oid_str(d.get("medicine_ref"))
    )
    with driver.session(database=NEO4J_DATABASE) as session:
        for batch in chunked(rows, BATCH_SIZE):
            session.run(CYPHER_LINK_MP_TO_MEDICINE, rows=batch)
    print("  OK")

    # 5) Link Medicine -> Substance
    print("[5/5] Linking Medicine -> Substance...")
    cur = col_m.find({}, {"_id": 1, "substance_ref_ids": 1})
    rel_rows: List[Dict[str, str]] = []
    with driver.session(database=NEO4J_DATABASE) as session:
        for mdoc in cur:
            mid = oid_str(mdoc["_id"])
            if not mid:
                continue
            for sid in extract_substance_ref_ids(mdoc):
                rel_rows.append({"medicine_mongo_id": mid, "substance_mongo_id": sid})
                if len(rel_rows) >= BATCH_SIZE:
                    session.run(CYPHER_LINK_MED_TO_SUB, rows=rel_rows)
                    rel_rows = []
        if rel_rows:
            session.run(CYPHER_LINK_MED_TO_SUB, rows=rel_rows)
    print("  OK")

    driver.close()
    print("\nDONE ✅")


if __name__ == "__main__":
    main()
