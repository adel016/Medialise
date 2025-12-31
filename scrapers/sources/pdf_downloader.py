# scrapers/sources/pdf_downloader.py
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


@dataclass
class PdfDownloadResult:
    url: str
    source: str              # "ansm" | "ema" | "other"
    local_path: str
    sha256: str
    size_bytes: int


def _guess_source(pdf_url: str) -> str:
    u = pdf_url.lower()
    if "ema.europa.eu" in u:
        return "ema"
    if "base-donnees-publique.medicaments.gouv.fr" in u:
        return "ansm"
    return "other"


def _safe_filename_from_url(pdf_url: str) -> str:
    # garde une partie lisible du nom de fichier
    name = pdf_url.split("?", 1)[0].rstrip("/").split("/")[-1] or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    # nettoyage minimal
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name


def download_pdf(
    pdf_url: str,
    out_root_dir: str,
    cis: Optional[str] = None,
    timeout_s: int = 40,
) -> PdfDownloadResult:
    """
    Télécharge un PDF sur disque (stream), calcule sha256, retourne métadonnées.
    Stockage:
      <out_root_dir>/<source>/<cis or 'unknown'>/<filename>.pdf
    """
    source = _guess_source(pdf_url)
    cis_dir = cis if cis else "unknown"

    out_dir = Path(out_root_dir) / source / cis_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename_from_url(pdf_url)
    out_path = out_dir / filename

    # Si déjà présent, on recalcule le hash (évite re-download)
    if out_path.exists() and out_path.stat().st_size > 0:
        sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
        return PdfDownloadResult(
            url=pdf_url,
            source=source,
            local_path=str(out_path),
            sha256=sha,
            size_bytes=out_path.stat().st_size,
        )

    r = requests.get(pdf_url, timeout=timeout_s, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    # sécurité : si le serveur ne renvoie pas du PDF, on évite d’écrire n’importe quoi
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "pdf" not in ctype and not pdf_url.lower().endswith(".pdf"):
        raise ValueError(f"Réponse non-PDF pour {pdf_url} (Content-Type={ctype})")

    sha256 = hashlib.sha256()
    size = 0

    tmp_path = str(out_path) + ".part"
    with open(tmp_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if not chunk:
                continue
            f.write(chunk)
            sha256.update(chunk)
            size += len(chunk)

    os.replace(tmp_path, out_path)

    return PdfDownloadResult(
        url=pdf_url,
        source=source,
        local_path=str(out_path),
        sha256=sha256.hexdigest(),
        size_bytes=size,
    )
