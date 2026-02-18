# scrapers/run_agno.py
import time
import argparse
import pandas as pd

from scrapers.sources.ansm_html import scrape_html
from scrapers.import_json_to_mongo import upsert_document
from scrapers.sources.ansm_extrait import scrape_extrait
from scrapers.sources.bdpm_cis import iter_cis_codes
from scrapers.sources.pdf_downloader import download_pdf
from scrapers.sources.bdpm_cpd import enrich_medicines_with_cpd
from scrapers.sources.bdpm_smr_asmr import enrich_medicines_with_smr_asmr
from scrapers.sources.bdpm_compo import enrich_medicines_with_compo
from scrapers.sources.pubchem import (
    enrich_medicines_with_pubchem,
    enrich_substances_with_pubchem_full,
)
from scrapers.sources.drugbank import ingest_drugbank
from scrapers.sources.openfda_ndc import ingest_openfda_ndc
from scrapers.utils.mongo import get_collection





from scrapers.pipeline.source_context import SourceContext, inject_source_context

BDPM_CIS_PATH = "data/bdpm/CIS_bdpm.csv"
BDPM_CPD_PATH = "data/bdpm/CIS_CPD_bdpm.csv"
BDPM_ASMR_PATH = "data/bdpm/CIS_HAS_ASMR_bdpm.csv"
BDPM_SMR_PATH = "data/bdpm/CIS_HAS_SMR_bdpm.csv"
BDPM_COMPO_PATH = "data/bdpm/CIS_COMPO_bdpm.csv"

EXCEL_PATH = "frontend_backend/scripts/liens_R.xlsx"
SHEET_NAME = "liens_R"
URL_COLUMN = "liens"
PDF_OUT_ROOT = "data/pdfs"

CTX_FR_BDPM_RCP_HTML = SourceContext(
    country="FR",
    authority="ANSM/BDPM",
    lang="fr",
    site="bdpm",
    doc_type="RCP_HTML",
    dataset="BDPM",
)

CTX_FR_BDPM_EXTRAIT = SourceContext(
    country="FR",
    authority="ANSM/BDPM",
    lang="fr",
    site="bdpm",
    doc_type="EXTRAIT_HTML",
    dataset="BDPM",
)


def normalize_url(url: str) -> str:
    return str(url).split("#", 1)[0].strip()


def run_batch(limit: int | None = None, sleep_s: float = 0.2):
    """Scraping ANSM/BDPM RCP HTML via l'Excel (liens_R.xlsx)"""
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)

    if URL_COLUMN not in df.columns:
        raise ValueError(
            f"Colonne '{URL_COLUMN}' introuvable dans {EXCEL_PATH}. "
            f"Colonnes disponibles: {list(df.columns)}"
        )

    urls = (
        df[URL_COLUMN]
        .dropna()
        .map(normalize_url)
        .loc[lambda s: s.str.len() > 0]
        .drop_duplicates()
        .tolist()
    )

    if limit is not None:
        urls = urls[:limit]

    total = len(urls)
    print(f"{total} URL(s) à traiter (sheet='{SHEET_NAME}', colonne='{URL_COLUMN}')")

    ok = 0
    ko = 0

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{total}] {url}")
        try:
            doc = scrape_html(url)
            doc = inject_source_context(doc, CTX_FR_BDPM_RCP_HTML)
            upsert_document(doc)
            ok += 1
        except Exception as e:
            ko += 1
            print(f"  ❌ ERREUR: {e}")

        if sleep_s > 0:
            time.sleep(sleep_s)

    print("\n=== TERMINÉ ANSM|HTML ===")
    print(f"✔ OK : {ok}")
    print(f"❌ KO : {ko}")


def run_bdpm_extrait_batch(limit: int | None = None, sleep_s: float = 0.2, download_pdfs: bool = True):
    """Scraping BDPM /extrait via CIS_bdpm.csv + téléchargement PDFs si demandé"""
    cis_list = iter_cis_codes(BDPM_CIS_PATH)

    if limit is not None:
        cis_list = cis_list[:limit]

    total = len(cis_list)
    print(f"{total} CIS à traiter (source BDPM: {BDPM_CIS_PATH})")

    ok = 0
    ko = 0

    for i, cis_code in enumerate(cis_list, start=1):
        extrait_url = f"https://base-donnees-publique.medicaments.gouv.fr/medicament/{cis_code}/extrait"
        print(f"[{i}/{total}] {extrait_url}")

        try:
            doc = scrape_extrait(extrait_url)
            doc = inject_source_context(doc, CTX_FR_BDPM_EXTRAIT)

            cis_meta = doc.get("metadata", {}).get("cis") or cis_code
            pdf_links = doc.get("pdf_links", [])
            print("   pdf_links:", len(pdf_links))

            if not download_pdfs:
                upsert_document(doc)
                ok += 1
                continue

            if not pdf_links:
                doc["pdf_downloads"] = []
                upsert_document(doc)
                ok += 1
                continue

            downloads = []
            for pdf_url in pdf_links:
                try:
                    res = download_pdf(pdf_url, out_root_dir=PDF_OUT_ROOT, cis=cis_meta)
                    downloads.append({
                        "url": res.url,
                        "source": res.source,
                        "local_path": res.local_path,
                        "sha256": res.sha256,
                        "size_bytes": res.size_bytes,
                    })
                    print(f"   ✅ téléchargé: {res.local_path}")
                except Exception as e:
                    downloads.append({"url": pdf_url, "error": str(e)})
                    print(f"   ❌ download error: {pdf_url} -> {e}")

            doc["pdf_downloads"] = downloads
            upsert_document(doc)
            ok += 1

        except Exception as e:
            ko += 1
            print(f"  ❌ ERREUR: {e}")

        if sleep_s > 0:
            time.sleep(sleep_s)

    print("\n=== TERMINÉ BDPM /extrait ===")
    print(f"✔ OK : {ok}")
    print(f"❌ KO : {ko}")


def run_cpd_enrichment(sleep_s: float = 0.0):
    stats = enrich_medicines_with_cpd(
        collection_name="medicines",
        cpd_path=BDPM_CPD_PATH,
        sleep_s=sleep_s,
    )
    print("\n=== TERMINÉ BDPM CPD (enrichissement) ===")
    print(f"Docs scannés : {stats['scanned']}")
    print(f"Docs avec CPD: {stats['with_cpd']}")
    print(f"Docs modifiés: {stats['modified']}")


def run_smr_asmr_enrichment(sleep_s: float = 0.0):
    stats = enrich_medicines_with_smr_asmr(
        collection_name="medicines",
        asmr_path=BDPM_ASMR_PATH,
        smr_path=BDPM_SMR_PATH,
        sleep_s=sleep_s,
    )
    print("\n=== TERMINÉ BDPM SMR/ASMR (enrichissement) ===")
    print(f"Docs scannés : {stats['scanned']}")
    print(f"Docs avec SMR/ASMR: {stats['with_any_smr_asmr']}")
    print(f"Docs modifiés: {stats['modified']}")


def run_compo_enrichment(sleep_s: float = 0.0):
    stats = enrich_medicines_with_compo(
        collection_name="medicines",
        compo_path=BDPM_COMPO_PATH,
        sleep_s=sleep_s,
    )
    print("\n=== TERMINÉ BDPM COMPO (enrichissement) ===")
    print(f"Docs scannés : {stats['scanned']}")
    print(f"Docs avec COMPO: {stats['with_compo']}")
    print(f"Docs modifiés: {stats['modified']}")


def run_theriaque_enrichment(*, theriaque_phpsessid: str | None, theriaque_authchallenge: str | None, limit: int | None = None):
    """Enrichissement Thériaque INTER (interactions médicamenteuses)"""
    from scrapers.agno_agent import enrich_theriaque_interactions_impl

    print("[THERIAQUE] run_theriaque_enrichment() CALLED")

    if not theriaque_phpsessid or not theriaque_authchallenge:
        print("[THERIAQUE] ❌ Cookies manquants.")
        print("  -> Fournis: --theriaque-phpsessid + --theriaque-authchallenge")
        return

    result = enrich_theriaque_interactions_impl(
        theriaque_phpsessid=theriaque_phpsessid,
        theriaque_authchallenge=theriaque_authchallenge,
        limit=limit,
    )


    print("\n=== TERMINÉ THÉRIAQUE INTERACTIONS ===")
    print(result)

def run_theriaque_c_indic_enrichment(*, theriaque_phpsessid: str | None, theriaque_authchallenge: str | None, limit: int | None = None):
    """Enrichissement Thériaque C_INDIC (contre-indications)"""
    from scrapers.agno_agent import enrich_theriaque_c_indic_impl

    print("[THERIAQUE] run_theriaque_c_indic_enrichment() CALLED")

    if not theriaque_phpsessid or not theriaque_authchallenge:
        print("[THERIAQUE] ❌ Cookies manquants.")
        print("  -> Fournis: --theriaque-phpsessid + --theriaque-authchallenge")
        return

    result = enrich_theriaque_c_indic_impl(
        theriaque_phpsessid=theriaque_phpsessid,
        theriaque_authchallenge=theriaque_authchallenge,
        limit_docs=limit,
    )

    print("\n=== TERMINÉ THÉRIAQUE CONTRE-INDICATIONS (C_INDIC) ===")
    print(result)

def run_theriaque_indic_enrichment(*, theriaque_phpsessid: str | None, theriaque_authchallenge: str | None, limit: int | None = None):
    """Enrichissement Thériaque INDIC (indications)"""
    from scrapers.agno_agent import enrich_theriaque_indic_impl

    print("[THERIAQUE] run_theriaque_indic_enrichment() CALLED")

    if not theriaque_phpsessid or not theriaque_authchallenge:
        print("[THERIAQUE] ❌ Cookies manquants.")
        print("  -> Fournis: --theriaque-phpsessid + --theriaque-authchallenge")
        return

    result = enrich_theriaque_indic_impl(
        theriaque_phpsessid=theriaque_phpsessid,
        theriaque_authchallenge=theriaque_authchallenge,
        limit_docs=limit,
    )

    print("\n=== TERMINÉ THÉRIAQUE INDICATIONS (INDIC) ===")
    print(result)


def run_pubchem_enrichment(
    *,
    limit: int | None = None,
    sleep_s: float = 0.2,
    save_images: bool = False,
    only_retryable_errors: bool = False,
):
    """
    Wrapper CLI pour l'enrichissement PubChem V3 (substances).
    """

    stats = enrich_substances_with_pubchem_full(
        collection_name="substances_v3",
        limit_docs=limit,
        sleep_s=sleep_s,
        synonyms_top_n=200,
        store_full_record=True,
        full_sections_collection="pubchem_compound_sections",
        download_images=save_images,
        images_out_dir="data/pubchem_images",
        only_retryable_errors=only_retryable_errors,
    )

    print("\n=== TERMINÉ PUBCHEM V3 (substances full) ===")

    if not stats:
        print("❌ ERREUR: enrich_substances_with_pubchem_full() a retourné None.")
        return

    print(f"Substances scannées : {stats.get('scanned', 0)}")
    print(f"CID matchés : {stats.get('matched', 0)}")
    print(f"Substances modifiées : {stats.get('updated', 0)}")
    print(f"Sans CID : {stats.get('no_cid', 0)}")
    print(f"Full record stockés : {stats.get('stored_full', 0)}")
    print(f"Images OK : {stats.get('images_ok', 0)}")
    print(f"Images échouées : {stats.get('images_fail', 0)}")

    if stats.get("errors"):
        print("Erreurs (extraits):")
        for e in stats["errors"]:
            print(" -", e)



def run_rcp_v3_from_medicine_market(limit: int | None = None, sleep_s: float = 0.2):
    mm = get_collection("medicine_market")

    query = {"source_urls": {"$elemMatch": {"$regex": r"[?&]typedoc=R\b"}}}
    proj = {"_id": 1, "cis": 1, "source_urls": 1}

    cursor = mm.find(query, proj)
    if limit is not None:
        cursor = cursor.limit(int(limit))

    ok = ko = scanned = 0
    for doc in cursor:
        scanned += 1
        urls = doc.get("source_urls") or []
        rcp_url = next((u for u in urls if isinstance(u, str) and "typedoc=R" in u), None)
        if not rcp_url:
            continue

        if scanned % 100 == 0:
            print(f"[RCP_V3] scanned={scanned} ok={ok} ko={ko}", flush=True)

        try:
            rcp_doc = scrape_html(rcp_url)

            mm.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "rcp.metadata": rcp_doc.get("metadata"),
                    "rcp.sections": rcp_doc.get("sections"),   # tu veux garder 'sections'
                    "rcp.meta_ingest": {
                        "source": "ansm_html",
                        "url": rcp_url,
                        "ingested_at": int(time.time()),
                    },
                    "updated_at": int(time.time()),
                }},
            )
            ok += 1

        except Exception as e:
            ko += 1
            print(f"[RCP_V3] ❌ cis={doc.get('cis')} url={rcp_url} err={e}")

        if sleep_s > 0:
            time.sleep(sleep_s)

    print("\n=== DONE RCP_V3 ===")
    print(f"scanned={scanned} ok={ok} ko={ko}")


def main():
    parser = argparse.ArgumentParser(description="MEDIALISE - pipeline scraping/enrichissement")
    parser.add_argument(
        "--mode",
        choices=["ansm_html", "bdpm_extrait", "cpd", "smr_asmr", "compo", "theriaque", "theriaque_c_indic", "theriaque_indic", "pubchem", "openfda_ndc", "all", "v2_to_v3_merge", "rcp_v3"],
        default="ansm_html",
        help="ansm_html=RCP HTML via Excel, bdpm_extrait=/extrait via CIS_bdpm.csv, cpd=CPD, smr_asmr=SMR+ASMR, compo=COMPO, theriaque=INTER, all=tout",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limite le nombre d'items (URLs ou CIS)")
    parser.add_argument("--sleep", type=float, default=0.2, help="Pause entre items (secondes)")
    parser.add_argument("--no-pdf", action="store_true", help="Désactive le téléchargement des PDFs en mode bdpm_extrait/all")

    parser.add_argument("--theriaque-phpsessid", type=str, default=None, help="Cookie Thériaque PHPSESSID")
    parser.add_argument("--theriaque-authchallenge", type=str, default=None, help="Cookie Thériaque authchallenge")

    parser.add_argument("--pubchem-save-images", action="store_true", help="Télécharge les PNG 2D PubChem en local")
    parser.add_argument(
    "--only-retryable-errors",
    action="store_true",
    help="Relancer uniquement les erreurs PubChem retryables (503, ServerBusy)"
)
    parser.add_argument("--drugbank-xml", dest="drugbank_xml", default=None,
                    help="Chemin vers drugbank_all_full_database.xml.zip")
    parser.add_argument("--drugbank-limit", dest="drugbank_limit", type=int, default=None,
                        help="Limite de drugs à ingérer (test rapide)")
    parser.add_argument("--drugbank-log-every", dest="drugbank_log_every", type=int, default=100,
                        help="Logs toutes les N entrées")
    parser.add_argument("--drugbank-no-raw-chunks", dest="drugbank_no_raw_chunks", action="store_true",
                        help="Désactive stockage des gros blocs en chunks (non recommandé)")
    parser.add_argument("--drugbank-dry-run", dest="drugbank_dry_run", action="store_true",
                        help="Parse mais n'écrit rien dans Mongo")


    parser.add_argument("--openfda-ndc", action="store_true", help="Ingestion OpenFDA drug/ndc -> medicine_market (US)")
    parser.add_argument("--openfda-limit", type=int, default=None, help="Limite total records OpenFDA")
    parser.add_argument("--openfda-since", type=str, default=None, help="Filtre marketing_start_date >= YYYYMMDD (OpenFDA drug/ndc)")
    parser.add_argument("--openfda-log-every", type=int, default=500, help="Logs toutes les N entrées OpenFDA")
    parser.add_argument("--openfda-dry-run", action="store_true", help="OpenFDA: parse mais n'écrit rien")



    args = parser.parse_args()
    # =========================
    # EARLY EXIT: DrugBank only
    # =========================
    if args.drugbank_xml:
        import os

        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        mongo_db = os.getenv("MONGO_DB", "medicsearch")  # ton .env dit medicsearch :contentReference[oaicite:3]{index=3}

        print(f"[DrugBank] ingest path={args.drugbank_xml}")
        print(f"[DrugBank] mongo_db={mongo_db} limit={args.drugbank_limit}")

        out = ingest_drugbank(
            xml_or_zip_path=args.drugbank_xml,
            mongo_uri=mongo_uri,
            mongo_db=mongo_db,
            limit=args.drugbank_limit,
            log_every=args.drugbank_log_every,
            store_raw_chunks=not args.drugbank_no_raw_chunks,
            dry_run=args.drugbank_dry_run,
        )
        print(f"[DrugBank] DONE: {out}")
        raise SystemExit(0)

    download_pdfs = not args.no_pdf

    if args.mode == "ansm_html":
        run_batch(limit=args.limit, sleep_s=args.sleep)
        return

    if args.mode == "bdpm_extrait":
        run_bdpm_extrait_batch(limit=args.limit, sleep_s=args.sleep, download_pdfs=download_pdfs)
        return

    if args.mode == "cpd":
        run_cpd_enrichment(sleep_s=args.sleep)
        return

    if args.mode == "smr_asmr":
        run_smr_asmr_enrichment(sleep_s=args.sleep)
        return

    if args.mode == "compo":
        run_compo_enrichment(sleep_s=args.sleep)
        return

    if args.mode == "theriaque":
        run_theriaque_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
            limit=args.limit,
        )
        return
    
    if args.mode == "theriaque_c_indic":
        run_theriaque_c_indic_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
            limit=args.limit,
        )
        return

    if args.mode == "theriaque_indic":
        run_theriaque_indic_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
            limit=args.limit,
        )
        return
    if args.mode == "pubchem":
        run_pubchem_enrichment(
            limit=args.limit, 
            sleep_s=args.sleep, 
            save_images=args.pubchem_save_images,
            only_retryable_errors=args.only_retryable_errors,
        )
        return

    # =========================
    # MODE: OpenFDA NDC
    # =========================
    if args.mode == "openfda_ndc":
        out = ingest_openfda_ndc(
            limit=args.openfda_limit if args.openfda_limit is not None else args.limit,
            since=args.openfda_since,
            log_every=args.openfda_log_every,
            dry_run=args.openfda_dry_run,
        )
        print(f"[OPENFDA] DONE: {out}")
        return
    
    if args.mode == "rcp_v3":
        run_rcp_v3_from_medicine_market(limit=args.limit, sleep_s=args.sleep)
        return

    if args.mode == "v2_to_v3_merge":
        run_v2_to_v3_merge(limit=args.limit)
        return


    if args.mode == "all":
        run_batch(limit=args.limit, sleep_s=args.sleep)
        run_bdpm_extrait_batch(limit=args.limit, sleep_s=args.sleep, download_pdfs=download_pdfs)
        run_cpd_enrichment(sleep_s=args.sleep)
        run_smr_asmr_enrichment(sleep_s=args.sleep)
        run_compo_enrichment(sleep_s=args.sleep)
        run_theriaque_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
        )
        run_theriaque_c_indic_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
            limit=args.limit,
        )
        run_theriaque_indic_enrichment(
            theriaque_phpsessid=args.theriaque_phpsessid,
            theriaque_authchallenge=args.theriaque_authchallenge,
            limit=args.limit,
        )
        run_pubchem_enrichment(
            limit=args.limit, 
            sleep_s=args.sleep, 
            save_images=args.pubchem_save_images,
            )
        return
    

def _safe_get(d: dict, path: str, default=None):
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur

def _dedup_by_hash(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        h = _safe_get(it, "metadata.content_hash") or it.get("content_hash")
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        out.append(it)
    return out


def run_v2_to_v3_merge(limit: int | None = None):
    """
    Merge V2 -> V3 sans casser V3:
    - lit medicines_v2_backup en legacy
    - jointure par CIS (V2: bdpm.cis) -> (V3: medicine_market.cis)
    - push dans medicine_market.rcp.migrations.v2 + medicine_market.theriaque.migrations.v2
    - optionnel: si V3 n'a pas rcp/theriaque, on peut aussi remplir 'rcp'/'theriaque' (active)
    """
    # Legacy collections (V2)
    import os
    os.environ["MEDICSEARCH_LEGACY"] = "1"
    v2 = get_collection("medicines_v2_backup")  # d’après ta capture
    os.environ.pop("MEDICSEARCH_LEGACY", None)

    # V3 target
    mm = get_collection("medicine_market")

    cursor = v2.find({}, {"bdpm.cis": 1, "url": 1, "metadata": 1, "sections": 1, "theriaque": 1})
    if limit is not None:
        cursor = cursor.limit(int(limit))

    ok = ko = scanned = 0
    for doc in cursor:
        scanned += 1
        cis = _safe_get(doc, "bdpm.cis")
        if not cis:
            ko += 1
            continue

        # Build payloads from V2
        rcp_v2_payload = None
        if doc.get("sections") is not None or doc.get("metadata") is not None:
            rcp_v2_payload = {
                "source": {
                    "origin": "v2",
                    "collection": "medicines_v2_backup",
                    "doc_id": str(doc.get("_id")),
                    "url": doc.get("url"),
                    "migrated_at": int(time.time()),
                },
                "metadata": doc.get("metadata"),
                "sections": doc.get("sections"),
            }

        theriaque_v2_payload = None
        if isinstance(doc.get("theriaque"), dict) and doc["theriaque"]:
            theriaque_v2_payload = {
                "source": {
                    "origin": "v2",
                    "collection": "medicines_v2_backup",
                    "doc_id": str(doc.get("_id")),
                    "migrated_at": int(time.time()),
                },
                **doc["theriaque"],
            }

        try:
            # 1) push migrations arrays (non destructif)
            update = {"$set": {"updated_at": int(time.time())}}
            if rcp_v2_payload:
                update.setdefault("$push", {}).setdefault("rcp.migrations.v2", {"$each": [rcp_v2_payload]})
            if theriaque_v2_payload:
                update.setdefault("$push", {}).setdefault("theriaque.migrations.v2", {"$each": [theriaque_v2_payload]})

            res = mm.update_one({"cis": str(cis)}, update)
            if res.matched_count == 0:
                # pas de market trouvé pour ce CIS -> on log, on ne crée pas de doc market (sinon ça pollue)
                ko += 1
                continue

            ok += 1

            # 2) dédup: on relit le doc et on déduplique les migrations par content_hash
            # (optionnel mais pratique pour éviter inflation si tu relances)
            target = mm.find_one({"cis": str(cis)}, {"rcp.migrations.v2": 1})
            mig = _safe_get(target or {}, "rcp.migrations.v2", [])
            if isinstance(mig, list) and mig:
                deduped = _dedup_by_hash(mig)
                if len(deduped) != len(mig):
                    mm.update_one({"cis": str(cis)}, {"$set": {"rcp.migrations.v2": deduped}})

            if scanned % 200 == 0:
                print(f"[V2->V3 MERGE] scanned={scanned} ok={ok} ko={ko}", flush=True)

        except Exception as e:
            ko += 1
            print(f"[V2->V3 MERGE] ❌ cis={cis} err={e}")

    print("\n=== DONE V2->V3 MERGE ===")
    print(f"scanned={scanned} ok={ok} ko={ko}")



if __name__ == "__main__":
    main()
