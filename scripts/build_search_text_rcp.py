# scripts/build_search_text_rcp.py
import os
import re
import hashlib
from datetime import datetime, timezone
from pymongo import MongoClient, UpdateOne

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "medicsearch")
COLL_NAME = os.getenv("MONGO_COLL", "medicines")

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))
DRY_RUN = os.getenv("DRY_RUN", "1") == "1"
ONLY_SCHEMA_V2 = os.getenv("ONLY_SCHEMA_V2", "1") == "1"

def norm_ws(s: str) -> str:
    s = s.replace("\u00a0", " ")  # nbsp
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def strip_html(s: str) -> str:
    # au cas où certains champs contiennent du html (ai_summary etc.)
    s = re.sub(r"<[^>]+>", " ", s)
    return norm_ws(s)

def collect_rcp_text(doc: dict) -> str:
    parts = []

    # --- drug ---
    drug = doc.get("drug") or {}
    for k in ("name", "title"):
        if drug.get(k):
            parts.append(str(drug.get(k)))

    # substances / dosages / forme / labo (selon ton schéma)
    for key in ("substances_actives", "active_substances", "substances"):
        val = drug.get(key)
        if isinstance(val, list):
            parts.extend([str(x) for x in val if x])
        elif isinstance(val, str) and val:
            parts.append(val)

    for key in ("dosages", "strengths"):
        val = drug.get(key)
        if isinstance(val, list):
            parts.extend([str(x) for x in val if x])
        elif isinstance(val, str) and val:
            parts.append(val)

    for key in ("forme", "form", "laboratoire", "laboratory", "holder"):
        if drug.get(key):
            parts.append(str(drug.get(key)))

    # --- rcp sections ---
    rcp = doc.get("rcp") or {}
    sections = rcp.get("sections") or rcp.get("content") or []
    # on supporte: sections=[{title, content:[{text}], subsections:[]}, ...]
    def walk_sections(sec_list):
        for sec in sec_list or []:
            title = sec.get("title")
            if title:
                parts.append(str(title))
            content = sec.get("content") or []
            for block in content:
                if isinstance(block, dict) and block.get("text"):
                    parts.append(str(block["text"]))
                elif isinstance(block, str):
                    parts.append(block)
            walk_sections(sec.get("subsections") or [])
    if isinstance(sections, list):
        walk_sections(sections)

    # --- document metadata (optionnel) ---
    document = doc.get("document") or {}
    if document.get("title"):
        parts.append(str(document["title"]))

    # final
    raw = " ".join(parts)
    raw = strip_html(raw).lower()
    return raw

def compute_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def main():
    client = MongoClient(MONGO_URI)
    coll = client[DB_NAME][COLL_NAME]

    query = {}
    if ONLY_SCHEMA_V2:
        query["schema_version"] = 2

    # On ne met à jour que ceux qui n'ont pas de search_text ou dont le hash diffère
    projection = {
        "_id": 1,
        "schema_version": 1,
        "drug": 1,
        "rcp": 1,
        "document": 1,
    }


    cursor = coll.find(query, projection=projection, no_cursor_timeout=True)
    ops = []
    processed = 0
    updated = 0

    try:
        for doc in cursor:
            processed += 1
            text = collect_rcp_text(doc)

            # petit garde-fou: si vide, on évite de polluer
            if len(text) < 10:
                continue

            new_hash = compute_hash(text)
            old_hash = ((doc.get("rcp") or {}).get("search_text_hash")) or None

            if old_hash == new_hash and ((doc.get("rcp") or {}).get("search_text")):
                continue

            update = {
                "$set": {
                    "rcp.search_text": text,
                    "rcp.search_text_hash": new_hash,
                    "rcp.search_text_updated_at": datetime.now(timezone.utc),
                }
            }
            ops.append(UpdateOne({"_id": doc["_id"]}, update))
            updated += 1

            if len(ops) >= BATCH_SIZE:
                if DRY_RUN:
                    print(f"[DRY_RUN] batch prêt: {len(ops)} (processed={processed}, à_maj≈{updated})")
                    ops.clear()
                else:
                    res = coll.bulk_write(ops, ordered=False)
                    print(f"[OK] bulk: matched={res.matched_count} modified={res.modified_count} (processed={processed})")
                    ops.clear()

        # last batch
        if ops:
            if DRY_RUN:
                print(f"[DRY_RUN] batch prêt: {len(ops)} (processed={processed}, à_maj≈{updated})")
            else:
                res = coll.bulk_write(ops, ordered=False)
                print(f"[OK] bulk: matched={res.matched_count} modified={res.modified_count} (processed={processed})")

    finally:
        cursor.close()

    print("Terminé.")
    print(f"Docs parcourus: {processed}")
    print(f"Docs à mettre à jour: {updated}")
    print(f"DRY_RUN={DRY_RUN}")

if __name__ == "__main__":
    main()
