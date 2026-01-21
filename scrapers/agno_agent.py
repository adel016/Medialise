# scrapers/agno_agent.py
from dotenv import load_dotenv
load_dotenv()

import time
import requests

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool

from scrapers.sources.ansm_html import scrape_html
from scrapers.sources.bdpm_cpd import enrich_medicines_with_cpd
from scrapers.import_json_to_mongo import upsert_document, import_all_from_test_outputs
from scrapers.sources.theriaque_html import (
    fetch_theriaque_c_indic, parse_theriaque_c_indic,
    fetch_theriaque_indic, parse_theriaque_indic,
)



from scrapers.sources.theriaque_html import (
    fetch_theriaque_interactions,
    resolve_sp_id_from_cis,
)
from scrapers.utils.mongo import get_collection


@tool
def scrape_ansm_rcp_url(url: str) -> str:
    doc = scrape_html(url)
    n = upsert_document(doc)
    return f"Scraping OK. Mongo upsert: {n} document. URL={url}"


@tool
def enrich_bdpm_cpd() -> str:
    stats = enrich_medicines_with_cpd()
    return (
        "Enrichissement BDPM CPD terminé.\n"
        f"- Docs scannés: {stats.get('scanned')}\n"
        f"- Docs avec CPD: {stats.get('with_cpd')}\n"
        f"- Docs modifiés: {stats.get('updated') or stats.get('modified')}"
    )


@tool
def import_existing_test_outputs() -> str:
    import_all_from_test_outputs()
    return "Import des fichiers test_outputs terminé."


def _make_theriaque_session(*, phpsessid: str, authchallenge: str) -> requests.Session:
    s = requests.Session()

    # Headers "navigateur" (souvent nécessaire sur des sites avec anti-bot léger)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Referer": "https://www.theriaque.org/apps/recherche/rch_simple.php",
    })

    # IMPORTANT: Thériaque utilise au moins 2 cookies (vu dans ton DevTools)
    # -> on les met en host-only (sans domain) pour que requests les envoie à www.theriaque.org
    s.cookies.set("PHPSESSID", phpsessid, path="/")
    s.cookies.set("authchallenge", authchallenge, path="/")

    return s


def enrich_theriaque_interactions_impl(
    *,
    theriaque_phpsessid: str | None = None,
    theriaque_authchallenge: str | None = None,
    limit: int | None = None,
) -> str:
    """
    Enrichit Mongo avec Thériaque (bloc theriaque.*), matching par bdpm.cis.
    """
    if not theriaque_phpsessid or not theriaque_authchallenge:
        return (
            "THERIAQUE: cookies manquants.\n"
            "-> Fournis PHPSESSID + authchallenge (DevTools > Application > Cookies)."
        )

    collection = get_collection("medicines")
    session = _make_theriaque_session(
        phpsessid=theriaque_phpsessid,
        authchallenge=theriaque_authchallenge,
    )

    # Auth check fiable: on veut voir "Bienvenue" + "action=logout"
    try:
        test = session.get("https://www.theriaque.org/apps/recherche/rch_simple.php", timeout=30)
        html = test.text or ""
        ok = ("Bienvenue" in html) and ("action=logout" in html)
        if ok:
            print("[THERIAQUE] AUTH CHECK: logged in ✅")
        else:
            print("[THERIAQUE] AUTH CHECK: NOT logged in ❌")
            # debug utile (statut + un indice)
            print(f"[THERIAQUE] status={test.status_code} len_html={len(html)}")
            if "Veuillez vous identifier" in html:
                print("[THERIAQUE] -> Le site renvoie la page login.")
            return "THERIAQUE: Auth failed (cookies invalid/expired)."
    except Exception as e:
        return f"THERIAQUE: Auth check error: {e}"

    scanned = matched = updated = 0

    cursor = collection.find(
        {"bdpm.cis": {"$exists": True, "$ne": None}},
        {"_id": 1, "bdpm.cis": 1},
    )

    for doc in cursor:
        scanned += 1
        if limit is not None and scanned > limit:
            break

        cis = (doc.get("bdpm") or {}).get("cis")
        if not cis:
            continue

        if scanned % 100 == 0:
            print(f"[THERIAQUE] scanned={scanned} matched={matched} updated={updated}")

        try:
            sp_id = resolve_sp_id_from_cis(str(cis), session)
        except Exception as e:
            print(f"[THERIAQUE] resolve_sp_id_from_cis ERROR cis={cis}: {e}")
            continue

        if not sp_id:
            continue

        matched += 1

        try:
            interactions = fetch_theriaque_interactions(int(sp_id), session=session)
        except Exception as e:
            print(f"[THERIAQUE] fetch_theriaque_interactions ERROR sp_id={sp_id} cis={cis}: {e}")
            continue

        if not interactions:
            continue

        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "theriaque.meta": {
                        "source": "theriaque",
                        "cis": str(cis),
                        "sp_id": str(sp_id),
                        "matched_by": "cis",
                        "last_updated_at": int(time.time()),
                    },
                    "theriaque.interactions": interactions,
                }
            },
        )
        updated += 1

    return (
        "Enrichissement Thériaque INTER terminé.\n"
        f"- Docs scannés : {scanned}\n"
        f"- Docs matchés : {matched}\n"
        f"- Docs modifiés: {updated}"
    )


@tool
def enrich_theriaque_interactions() -> str:
    # Appel outil Agno "manuel" (sans cookies)
    return "Utilise la CLI: python -m scrapers.run_agno --mode theriaque --theriaque-phpsessid ... --theriaque-authchallenge ..."


agno_agent = Agent(
    name="Medical Data Scraper",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        scrape_ansm_rcp_url,
        enrich_bdpm_cpd,
        enrich_theriaque_interactions,
        import_existing_test_outputs,
    ],
    instructions=[
        "Tu automatises des pipelines de collecte de données médicales.",
        "Reste concis et technique.",
    ],
    markdown=True,
)


def enrich_theriaque_c_indic_impl(
    theriaque_phpsessid: str | None = None,
    theriaque_authchallenge: str | None = None,
    limit_docs: int | None = None
) -> str:
    collection = get_collection("medicines")

    if not theriaque_phpsessid or not theriaque_authchallenge:
        return "[THERIAQUE] Cookies manquants: --theriaque-phpsessid + --theriaque-authchallenge"

    session = _make_theriaque_session(
        phpsessid=theriaque_phpsessid,
        authchallenge=theriaque_authchallenge,
    )

    test = session.get("https://www.theriaque.org/apps/recherche/rch_simple.php", timeout=30)
    html = test.text or ""
    ok = ("Bienvenue" in html) and ("action=logout" in html)
    if not ok:
        return "[THERIAQUE] AUTH FAILED (cookies invalides/expirés)"

    scanned = matched = updated = 0

    cursor = collection.find(
        {"bdpm.cis": {"$exists": True, "$ne": None}},
        {"_id": 1, "bdpm.cis": 1}
    )

    if limit_docs is not None:
        cursor = cursor.limit(int(limit_docs))

    for doc in cursor:
        scanned += 1
        if scanned % 100 == 0:
            print(
                f"[THERIAQUE|C_INDIC] scanned={scanned} matched={matched} updated={updated}",
                flush=True
            )
        cis = (doc.get("bdpm") or {}).get("cis")
        if not cis:
            continue

        sp_id = resolve_sp_id_from_cis(str(cis), session)
        if not sp_id:
            continue
        matched += 1

        page = fetch_theriaque_c_indic(str(sp_id), session=session)
        parsed = parse_theriaque_c_indic(page["html"])

        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "theriaque.meta": {
                        "source": "theriaque",
                        "cis": str(cis),
                        "sp_id": str(sp_id),
                        "matched_by": "cis",
                        "last_updated_at": int(time.time()),
                    },
                    "theriaque.c_indic": {
                        "sp_id": str(sp_id),
                        "url": page["url"],
                        **parsed,
                    },
                }
            }
        )

        updated += 1

    return (
        "Enrichissement Thériaque C_INDIC terminé.\n"
        f"- Docs scannés : {scanned}\n"
        f"- Docs matchés : {matched}\n"
        f"- Docs modifiés: {updated}"
    )



def enrich_theriaque_indic_impl(
    theriaque_phpsessid: str | None = None,
    theriaque_authchallenge: str | None = None,
    limit_docs: int | None = None
) -> str:
    collection = get_collection("medicines")

    if not theriaque_phpsessid or not theriaque_authchallenge:
        return "[THERIAQUE] Cookies manquants: --theriaque-phpsessid + --theriaque-authchallenge"

    session = _make_theriaque_session(
        phpsessid=theriaque_phpsessid,
        authchallenge=theriaque_authchallenge,
    )

    test = session.get("https://www.theriaque.org/apps/recherche/rch_simple.php", timeout=30)
    html = test.text or ""
    ok = ("Bienvenue" in html) and ("action=logout" in html)
    if not ok:
        return "[THERIAQUE] AUTH FAILED (cookies invalides/expirés)"

    scanned = matched = updated = 0

    cursor = collection.find(
        {"bdpm.cis": {"$exists": True, "$ne": None}},
        {"_id": 1, "bdpm.cis": 1}
    )
    if limit_docs is not None:
        cursor = cursor.limit(int(limit_docs))

    for doc in cursor:
        scanned += 1

        # suivi toutes les 100 lignes
        if scanned % 100 == 0:
            print(f"[THERIAQUE|INDIC] scanned={scanned} matched={matched} updated={updated}", flush=True)

        cis = (doc.get("bdpm") or {}).get("cis")
        if not cis:
            continue

        sp_id = resolve_sp_id_from_cis(str(cis), session)
        if not sp_id:
            continue
        matched += 1

        page = fetch_theriaque_indic(str(sp_id), session=session)
        parsed = parse_theriaque_indic(page["html"])

        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "theriaque.meta": {
                        "source": "theriaque",
                        "cis": str(cis),
                        "sp_id": str(sp_id),
                        "matched_by": "cis",
                        "last_updated_at": int(time.time()),
                    },
                    "theriaque.indic": {
                        "sp_id": str(sp_id),
                        "url": page["url"],
                        **parsed,
                    },
                }
            }
        )
        updated += 1

    return (
        "Enrichissement Thériaque INDIC terminé.\n"
        f"- Docs scannés : {scanned}\n"
        f"- Docs matchés : {matched}\n"
        f"- Docs modifiés: {updated}"
    )
