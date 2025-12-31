from dotenv import load_dotenv
load_dotenv()

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import tool

from scrapers.sources.ansm_html import scrape_html
from scrapers.import_json_to_mongo import upsert_document, import_all_from_test_outputs


@tool
def scrape_ansm_rcp_url(url: str) -> str:
    """
    Scrape une page RCP ANSM en HTML à partir d'une URL,
    puis upsert dans MongoDB.
    """
    doc = scrape_html(url)
    n = upsert_document(doc)
    return f"Scraping OK. Mongo upsert: {n} document. URL={url}"


@tool
def import_existing_test_outputs() -> str:
    """
    Importe tous les fichiers JSON présents dans scrapers/test_outputs
    (ta fonction existante).
    """
    import_all_from_test_outputs()
    return "Import des fichiers test_outputs terminé."


agno_agent = Agent(
    name="Medical Data Scraper",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[scrape_ansm_rcp_url, import_existing_test_outputs],
    instructions=[
        "Tu automatises des tâches techniques de scraping et d'import.",
        "Quand on te donne une URL RCP ANSM HTML, utilise scrape_ansm_rcp_url(url).",
        "Reste concis."
    ],
    markdown=True,
)
