# scrapers/run_pdf_ingest.py

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from scrapers.utils.mongo import get_collection
from scrapers.utils.pdf_extract import extract_pdf
from scrapers.utils.sections_tree import build_sections_tree
from scrapers.utils.ema_title import extract_ema_title_from_sections, normalize_for_search

COL_MEDICINES = "medicines"
EMA_ROOT = os.path.join("data", "pdfs", "ema")


def iter_pdfs(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".pdf"):
                yield os.path.join(dirpath, fn)


def ema_id_from_path(pdf_path: str) -> str | None:
    parent = os.path.basename(os.path.dirname(pdf_path))
    if re.fullmatch(r"\d+", parent):
        return parent
    return None

def main():
    col = get_collection(COL_MEDICINES)

    # Index unique EMA (durable) : 1 doc par ema_id
    col.create_index(
        [("metadata.source", 1), ("metadata.ema_id", 1)],
        unique=True,
        partialFilterExpression={
            "metadata.source": "ema",
            "metadata.ema_id": {"$exists": True, "$type": "string"}
        }
    )

    pdf_paths = list(iter_pdfs(EMA_ROOT))
    total = len(pdf_paths)
    print(f"{total} PDF(s) EMA trouvés")

    from scrapers.utils.ema_smpc_parser import parse_smpc_sections  # ✅ Annexe I only

    for i, path in enumerate(pdf_paths, 1):
        ema_id = ema_id_from_path(path)
        if not ema_id:
            print(f"[{i}/{total}] ⚠️ ema_id introuvable → skip")
            continue

        key = {"metadata.source": "ema", "metadata.ema_id": ema_id}

        try:
            extraction = extract_pdf(path)

            # 1) Parser uniquement ANNEXE I (SmPC / RCP)
            rcp_sections = parse_smpc_sections(extraction.text)

            # 2) Construire l'arbre de sections (format v2)
            if rcp_sections:
                sections_tree = build_sections_tree(rcp_sections)
                extraction_status = "ok"
                extracted_title = extract_ema_title_from_sections(rcp_sections)
            else:
                sections_tree = []
                extraction_status = "no_annexe_i_found"
                extracted_title = None

            now = datetime.now(timezone.utc)

            # 3) Champs v2 + metadata stable
            set_fields = {
                "schema_version": 2,

                "metadata": {
                    "source": "ema",
                    "ema_id": ema_id,
                    "extraction_status": extraction_status,
                    "title_source": "ema_pdf_annexe_i" if extracted_title else None,
                    "search_title": normalize_for_search(extracted_title) if extracted_title else None,
                },

                "document": {
                    "scraped_at": now,
                    "content_hash": extraction.sha256,
                    "updated_at": None,
                },

                "drug": {
                    # Important : pour EMA, le "name" propre n'est pas garanti.
                    # On met le titre extrait (au moins on a un libellé exploitable).
                    "name": extracted_title or None,
                    "full_title": extracted_title or None,
                    "laboratory": None,
                    "form": None,
                    "active_substances": [],
                    "strengths": [],
                },

                "rcp": {
                    "sections": sections_tree,
                    "search_text": (extraction.text or "").lower(),
                    "search_text_hash": extraction.sha256,
                    "search_text_updated_at": now,
                },

                "source": {
                    "site": "ema",
                    "url": None,
                    "ema_id": ema_id,
                    "type_doc": "RCP",
                },

                "url": None,
                "last_scraped": now,

                # Debug (tu peux enlever plus tard)
                "_extracted_title_tmp": extracted_title,
            }

            # Nettoyage : si extracted_title est None, on évite d’écraser title_source/search_title par None
            if not extracted_title:
                set_fields["metadata"].pop("title_source", None)
                set_fields["metadata"].pop("search_title", None)
                set_fields.pop("_extracted_title_tmp", None)

            update = {"$set": set_fields}
            col.update_one(key, update, upsert=True)

            print(
                f"[{i}/{total}] ✅ EMA {ema_id} | status={extraction_status} "
                f"| sections={len(sections_tree)} | title={'OK' if extracted_title else 'None'}"
            )

        except Exception as e:
            print(f"[{i}/{total}] ❌ erreur inattendue EMA {ema_id}: {e}")


if __name__ == "__main__":
    main()
