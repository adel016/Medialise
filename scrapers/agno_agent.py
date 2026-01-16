from dotenv import load_dotenv
load_dotenv()

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool

from scrapers.sources.ansm_html import scrape_html
from scrapers.sources.bdpm_cpd import enrich_medicines_with_cpd
from scrapers.import_json_to_mongo import upsert_document, import_all_from_test_outputs


@tool
def scrape_ansm_rcp_url(url: str) -> str:
    """
    Scrape une page RCP ANSM en HTML puis upsert dans MongoDB.
    """
    doc = scrape_html(url)
    n = upsert_document(doc)
    return f"Scraping OK. Mongo upsert: {n} document. URL={url}"


@tool
def enrich_bdpm_cpd() -> str:
    """
    Enrichit les médicaments Mongo avec les conditions de prescription BDPM (CPD).
    """
    stats = enrich_medicines_with_cpd()
    return (
        "Enrichissement BDPM CPD terminé.\n"
        f"- Docs scannés: {stats['scanned']}\n"
        f"- Docs avec CPD: {stats['with_cpd']}\n"
        f"- Docs modifiés: {stats['updated']}"
    )


@tool
def import_existing_test_outputs() -> str:
    """
    Importe tous les fichiers JSON présents dans scrapers/test_outputs.
    """
    import_all_from_test_outputs()
    return "Import des fichiers test_outputs terminé."


agno_agent = Agent(
    name="Medical Data Scraper",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        scrape_ansm_rcp_url,
        enrich_bdpm_cpd,
        import_existing_test_outputs,
    ],
    instructions=[
        "Tu automatises des pipelines de collecte de données médicales.",
        "Utilise scrape_ansm_rcp_url(url) pour les RCP ANSM.",
        "Utilise enrich_bdpm_cpd() pour enrichir la base avec BDPM.",
        "Reste concis et technique."
    ],
    markdown=True,
)
