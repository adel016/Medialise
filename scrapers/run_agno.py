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


def main():
    parser = argparse.ArgumentParser(description="MEDIALISE - pipeline scraping/enrichissement")
    parser.add_argument(
        "--mode",
        choices=["ansm_html", "bdpm_extrait", "cpd", "smr_asmr", "compo", "theriaque", "theriaque_c_indic", "theriaque_indic", "pubchem", "all"],
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



    args = parser.parse_args()
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


if __name__ == "__main__":
    main()
