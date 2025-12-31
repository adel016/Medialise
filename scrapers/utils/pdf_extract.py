from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class PdfExtraction:
    sha256: str
    num_pages: int
    text: str
    pages: List[str]
    rcp_sections: Dict[str, str]  # {"1": "...", "4.1": "...", ...}


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def extract_text_pages(path: str) -> Tuple[List[str], str]:
    # PyMuPDF
    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        pages = [(page.get_text("text") or "") for page in doc]
        doc.close()
        return pages, "pymupdf"
    except Exception:
        pass

    # fallback pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(path)
        pages = [(p.extract_text() or "") for p in reader.pages]
        return pages, "pypdf"
    except Exception as e:
        raise RuntimeError(
            "Impossible d'extraire le texte. Installe PyMuPDF (recommandé) ou pypdf."
        ) from e


_RCP_HEADER_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)*)\.\s+(?P<title>[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ0-9'’ \-()/]+)\s*$",
    re.MULTILINE,
)


def split_rcp_sections(full_text: str) -> Dict[str, str]:
    matches = list(_RCP_HEADER_RE.finditer(full_text))
    if not matches:
        return {}

    sections: Dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        num = m.group("num").strip()
        title = m.group("title").strip()
        body = full_text[start:end].strip()
        sections[num] = f"{num}. {title}\n{body}".strip()
    return sections


def extract_pdf(path: str) -> PdfExtraction:
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    digest = sha256_file(path)
    try:
        pages, engine = extract_text_pages(path)
        full_text = "\n".join(pages).strip()
        rcp_sections = split_rcp_sections(full_text)
        extraction_status = "ok"
    except Exception:
        pages = []
        full_text = ""
        rcp_sections = {}
        extraction_status = "scanned_or_unreadable"
        engine = None


    return PdfExtraction(
        sha256=digest,
        num_pages=len(pages),
        text=full_text,
        pages=pages,
        rcp_sections=rcp_sections,
    )

