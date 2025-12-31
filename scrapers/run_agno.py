import time
import pandas as pd

from scrapers.sources.ansm_html import scrape_html
from scrapers.import_json_to_mongo import upsert_document
from scrapers.sources.ansm_extrait import scrape_extrait
from scrapers.sources.bdpm_cis import iter_cis_codes
from scrapers.sources.pdf_downloader import download_pdf

from scrapers.pipeline.source_context import SourceContext, inject_source_context


BDPM_CIS_PATH = "data/bdpm/CIS_bdpm.csv"

EXCEL_PATH = "frontend_backend/scripts/liens_R.xlsx"
SHEET_NAME = "liens_R"
URL_COLUMN = "liens"
PDF_OUT_ROOT = "data/pdfs"
DOWNLOAD_PDFS = True


# --- Contextes déclaratifs ---
CTX_FR_BDPM_RCP_HTML = SourceContext(
    country="FR",
    authority="ANSM/BDPM",
    lang="fr",
    site="bdpm",
    doc_type="RCP_HTML",
    dataset="BDPM"
)

CTX_FR_BDPM_EXTRAIT = SourceContext(
    country="FR",
    authority="ANSM/BDPM",
    lang="fr",
    site="bdpm",
    doc_type="EXTRAIT_HTML",
    dataset="BDPM"
)


def normalize_url(url: str) -> str:
    return str(url).split("#", 1)[0].strip()


def run_batch(limit: int | None = None, sleep_s: float = 0.2):
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

            # ✅ Injection déclarative (pas de déduction par URL)
            doc = inject_source_context(doc, CTX_FR_BDPM_RCP_HTML)

            upsert_document(doc)
            ok += 1
        except Exception as e:
            ko += 1
            print(f"  ❌ ERREUR: {e}")

        if sleep_s > 0:
            time.sleep(sleep_s)

    print("\n=== TERMINÉ ===")
    print(f"✔ OK : {ok}")
    print(f"❌ KO : {ko}")


def run_bdpm_extrait_batch(limit: int | None = None, sleep_s: float = 0.2):
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

            # ✅ Injection déclarative
            doc = inject_source_context(doc, CTX_FR_BDPM_EXTRAIT)

            cis_meta = doc.get("metadata", {}).get("cis") or cis_code
            pdf_links = doc.get("pdf_links", [])
            print("   pdf_links:", len(pdf_links))

            if not DOWNLOAD_PDFS:
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


if __name__ == "__main__":
    run_batch(limit=None, sleep_s=0.2) # lancement du scrapping ANSM|HTML
    #run_bdpm_extrait_batch(limit=None, sleep_s=0.2)
