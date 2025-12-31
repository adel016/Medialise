# scrapers/pipeline/source_context.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SourceContext:
    country: str           # "FR", "CA", "US", "EU"
    authority: str         # "ANSM/BDPM", "Health Canada", "FDA", "EMA"
    lang: str              # "fr", "en", ...
    site: str              # "bdpm", "health_canada", "fda", "ema"
    doc_type: str          # "RCP_HTML", "EXTRAIT_HTML", "EPAR_PDF", ...

    # Optionnel: utile si tu veux distinguer des sous-sources
    dataset: Optional[str] = None


def inject_source_context(doc: Dict[str, Any], ctx: SourceContext) -> Dict[str, Any]:
    """
    Injecte le contexte source dans doc["source"] (merge non destructif).
    Ne supprime rien. N'écrase pas si le champ est déjà présent.
    """
    if not isinstance(doc, dict):
        return doc

    src = doc.get("source")
    if not isinstance(src, dict):
        src = {}

    ctx_dict = {k: v for k, v in asdict(ctx).items() if v is not None}
    for k, v in ctx_dict.items():
        src.setdefault(k, v)

    doc["source"] = src
    return doc
