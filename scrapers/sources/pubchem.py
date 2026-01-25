# scrapers/sources/pubchem.py
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import unicodedata
import requests
from pymongo import UpdateOne
from scrapers.utils.mongo import get_collection
from pathlib import Path
import random



PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


# ----------------------------
# Helpers (cleaning / safety)
# ----------------------------
def _now_ts() -> int:
    return int(time.time())


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _ascii_fold(s: str) -> str:
    """
    Convertit accents → ASCII, et remplace le caractère cassé '�'.
    Déterministe.
    """
    s = _safe_str(s).replace("�", "e")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def _candidate_names_from_raw(raw_name: str) -> List[str]:
    """
    Génère quelques variantes *sans casser* la donnée d'origine.
    On garde toujours raw_name en premier, puis des variantes nettoyées.
    """
    raw = _normalize_spaces(_safe_str(raw_name))
    if not raw:
        return []

    variants: List[str] = [raw]

    # Variante 1: enlever dosage/parenthèses/crochets (souvent sources BDPM/ANSM)
    v1 = re.sub(r"\(.*?\)", " ", raw)
    v1 = re.sub(r"\[.*?\]", " ", v1)
    v1 = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|mcg|µg|ui|u\.i\.|ml|mmol|%)\b",
        " ",
        v1,
        flags=re.IGNORECASE,
    )
    v1 = _normalize_spaces(v1)
    if v1 and v1 not in variants:
        variants.append(v1)

    # Variante 2: couper sur séparateurs fréquents (ex: " - " / ",")
    v2 = re.split(r"\s*-\s*|,", raw, maxsplit=1)[0]
    v2 = _normalize_spaces(v2)
    if v2 and v2 not in variants:
        variants.append(v2)

    # Variante 3: enlever caractères non alphanum basiques (garde +, -, espaces)
    v3 = re.sub(r"[^A-Za-z0-9\-\+\s]", " ", raw)
    v3 = _normalize_spaces(v3)
    if v3 and v3 not in variants:
        variants.append(v3)

    return variants


def _requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
    )
    return s


def _get_json(session: requests.Session, url: str, *, timeout: float = 25.0) -> Dict[str, Any]:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ----------------------------
# Normalisation SA → PubChem
# ----------------------------

FORMULATION_STOPWORDS = [
    "concentrat",
    "forme huileuse",
    "forme",
    "huileuse",
    "synthétique",
    "synthetique",
    "pommade",
    "solution",
    "comprimé",
    "comprime",
    "capsule",
    "gel",
    "sirop",
    "suspension",
]

SALTS = [
    "acetate", "acétate",
    "sulfate", "sulphate",
    "chlorhydrate", "hydrochloride",
    "bromhydrate", "hydrobromide",
    "phosphate",
    "citrate",
    "tartrate",
    "mesilate", "mesylate",
    "besilate", "besylate",
    "fumarate",
    "maleate",
    "succinate",
    "lactate",
    "gluconate",
]

CHEMICAL_SYNONYMS = {
    "vitamine a": ["retinol", "vitamin a"],
    "vitamine c": ["ascorbic acid", "vitamin c"],
    "vitamine d": ["cholecalciferol", "vitamin d3", "vitamin d"],
    "vitamine b6": ["pyridoxine", "vitamin b6"],
    "vitamine b12": ["cobalamin", "vitamin b12"],
}

def normalize_sa_for_pubchem(raw_name: str) -> List[str]:
    """
    Fusion robuste :
    - garde les variantes existantes
    - ajoute règles FR->EN pour sels/esters
    - ajoute mapping minimal vitamines
    - ASCII fold pour gérer accents et '�'
    """
    queries: List[str] = []

    raw = _normalize_spaces(_safe_str(raw_name))
    if not raw:
        return []

    # 1) Variantes existantes (TA logique initiale)
    for q in _candidate_names_from_raw(raw):
        queries.append(q)

    # 2) ASCII fold version (accents, caractères cassés)
    folded = _ascii_fold(raw)
    folded = _normalize_spaces(folded)
    if folded and folded not in queries:
        queries.append(folded)

    low = folded.lower().replace("’", "'").replace("`", "'")

    # 3) Mapping minimal (vitamines etc.)
    for k, vals in CHEMICAL_SYNONYMS.items():
        if k in low:
            for v in vals:
                if v not in queries:
                    queries.append(v)

    # 4) Règle FR -> EN pour sels/esters : "sulfate d abacavir" -> "abacavir sulfate" + "abacavir"
    salts_norm = [_ascii_fold(s).lower() for s in SALTS]
    salts_pattern = "|".join(sorted(set(map(re.escape, salts_norm)), key=len, reverse=True))

    # On enlève juste les "de/d’" pour détecter le pattern
    base = re.sub(r"[^a-z0-9\s'\-]", " ", low)
    base = _normalize_spaces(base)

    base_no_de = re.sub(r"\b(d'|de|du|des|d)\b", " ", base)
    base_no_de = _normalize_spaces(base_no_de)

    m = re.match(rf"^(?P<salt>{salts_pattern})\s+(?:d'|de|du|des|d)\s+(?P<drug>.+)$", base)
    if m:
        salt = _normalize_spaces(m.group("salt"))
        drug = _normalize_spaces(m.group("drug"))
        q1 = f"{drug} {salt}"
        if q1 and q1 not in queries:
            queries.append(q1)
        if drug and drug not in queries:
            queries.append(drug)

    m2 = re.match(rf"^(?P<drug>.+?)\s+(?P<salt>{salts_pattern})$", base_no_de)
    if m2:
        drug = _normalize_spaces(m2.group("drug"))
        salt = _normalize_spaces(m2.group("salt"))
        q1 = f"{drug} {salt}"
        if q1 and q1 not in queries:
            queries.append(q1)
        if drug and drug not in queries:
            queries.append(drug)

    # 5) Déduplication (ordre conservé)
    seen = set()
    out: List[str] = []
    for q in queries:
        q2 = _normalize_spaces(_safe_str(q))
        if q2 and q2 not in seen:
            seen.add(q2)
            out.append(q2)

    return out


# ----------------------------
# PubChem API calls
# ----------------------------
def pubchem_name_to_cids(session: requests.Session, name: str) -> List[int]:
    name_path = requests.utils.quote(name, safe="")
    url = f"{PUBCHEM_BASE}/compound/name/{name_path}/cids/JSON"
    data = _get_json(session, url)
    cids = data.get("IdentifierList", {}).get("CID", [])
    if not isinstance(cids, list):
        return []
    out: List[int] = []
    for c in cids:
        try:
            out.append(int(c))
        except Exception:
            continue
    return out


def pubchem_cid_properties(session: requests.Session, cid: int) -> Dict[str, Any]:
    props = ",".join(
        [
            "MolecularFormula",
            "MolecularWeight",
            "CanonicalSMILES",
            "IsomericSMILES",
            "InChI",
            "InChIKey",
            "ExactMass",
        ]
    )
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/property/{props}/JSON"
    data = _get_json(session, url)
    props_list = data.get("PropertyTable", {}).get("Properties", [])
    if isinstance(props_list, list) and props_list:
        return props_list[0] if isinstance(props_list[0], dict) else {}
    return {}


def pubchem_cid_synonyms(session: requests.Session, cid: int, *, top_n: int = 20) -> List[str]:
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON"
    data = _get_json(session, url)
    info_list = data.get("InformationList", {}).get("Information", [])
    if not isinstance(info_list, list) or not info_list:
        return []
    first = info_list[0] if isinstance(info_list[0], dict) else {}
    syns = first.get("Synonym", [])
    if not isinstance(syns, list):
        return []
    out = [_normalize_spaces(_safe_str(x)) for x in syns]
    out = [x for x in out if x]
    return out[: max(0, int(top_n))]


def pubchem_cid_png_url(cid: int, *, image_size: str = "300x300") -> str:
    return f"{PUBCHEM_BASE}/compound/cid/{cid}/PNG?image_size={requests.utils.quote(image_size, safe='x')}"


def download_png(session: requests.Session, url: str, out_path: str, *, timeout: float = 25.0) -> None:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)


# ----------------------------
# Extraction SA depuis doc Mongo
# ----------------------------
def extract_active_substances(doc: Dict[str, Any]) -> List[str]:
    """
    Priorité:
    1) bdpm.compo_sa_substances (si list non vide)
    2) metadata.medicine_details.substances_actives (si list non vide)
    """
    out: List[str] = []

    bdpm = doc.get("bdpm") or {}
    sa = bdpm.get("compo_sa_substances")
    if isinstance(sa, list) and sa:
        for x in sa:
            s = _normalize_spaces(_safe_str(x))
            if s:
                out.append(s)

    if out:
        return out

    meta = doc.get("metadata") or {}
    details = meta.get("medicine_details") or {}
    sa2 = details.get("substances_actives")
    if isinstance(sa2, list) and sa2:
        for x in sa2:
            s = _normalize_spaces(_safe_str(x))
            if s:
                out.append(s)

    return out


# ----------------------------
# Enrichissement principal
# ----------------------------
@dataclass
class PubChemEnrichConfig:
    collection_name: str = "medicines"
    limit_docs: Optional[int] = None
    sleep_s: float = 0.2
    synonyms_top_n: int = 20

    save_images: bool = False
    image_dir: str = "data/pubchem/images"
    image_size: str = "300x300"


def enrich_medicines_with_pubchem(
    *,
    collection_name: str = "medicines",
    limit_docs: Optional[int] = None,
    sleep_s: float = 0.2,
    synonyms_top_n: int = 20,
    save_images: bool = False,
    image_dir: str = "data/pubchem/images",
    image_size: str = "300x300",
) -> Dict[str, Any]:
    """
    Enrichit chaque document ayant au moins une SA (via BDPM ou metadata) avec PubChem:
    - 1 CID (best) par SA (premier CID renvoyé)
    - propriétés: Formula, Weight, SMILES, InChI, InChIKey, ExactMass
    - synonymes (top_n)
    - URL image 2D (et téléchargement optionnel)
    Écrit dans: sources.pubchem
    Ne supprime rien de l'existant.
    """
    medicines = get_collection(collection_name)
    session = _requests_session()

    cursor = medicines.find(
        {
            "$or": [
                {"sources.pubchem": {"$exists": False}},
                {"sources.pubchem.compounds": {"$elemMatch": {"error": "no_cid_found"}}},
            ]
        },
        projection={"_id": 1, "url": 1, "bdpm": 1, "metadata": 1, "sources.pubchem": 1},
    )


    scanned = 0
    updated_docs = 0
    docs_with_sa = 0
    compounds_resolved = 0
    errors: List[str] = []

    def _has_any_best(pubchem_obj: Any) -> bool:
        if not isinstance(pubchem_obj, dict):
            return False
        comps = pubchem_obj.get("compounds")
        if not isinstance(comps, list):
            return False
        for c in comps:
            if isinstance(c, dict):
                best = c.get("best")
                if isinstance(best, dict) and best.get("cid"):
                    return True
        return False


    for doc in cursor:
        scanned += 1
        if scanned % 100 == 0:
            print(
                f"[PubChem] {scanned} docs scannés | "
                f"SA: {docs_with_sa} | "
                f"résolus: {compounds_resolved} | "
                f"modifiés: {updated_docs}"
            )
        if limit_docs is not None and scanned >= limit_docs:
            break

        doc_id = doc.get("_id")
        url = doc.get("url")

        sa_list = extract_active_substances(doc)
        if not sa_list:
            continue

        docs_with_sa += 1
        compounds: List[Dict[str, Any]] = []

        for raw_sa in sa_list:
            entry: Dict[str, Any] = {
                "input_name": raw_sa,
                "queries": [],
                "candidates": [],
                "best": None,
                "error": None,
            }
            entry["normalized_queries"] = normalize_sa_for_pubchem(raw_sa)


            try:
                cids: List[int] = []
                normalized_queries = normalize_sa_for_pubchem(raw_sa)
                for q in entry["normalized_queries"]:
                    entry["queries"].append(q)
                    try:
                        cids = pubchem_name_to_cids(session, q)
                    except requests.HTTPError as e:
                        if getattr(e.response, "status_code", None) == 404:
                            cids = []
                        else:
                            raise
                    if cids:
                        break

                if not cids:
                    entry["error"] = "no_cid_found"
                    compounds.append(entry)
                    continue

                entry["candidates"] = cids[:10]
                best_cid = int(cids[0])

                props = pubchem_cid_properties(session, best_cid)

                best: Dict[str, Any] = {
                    "cid": best_cid,
                    "molecular_formula": props.get("MolecularFormula"),
                    "molecular_weight": props.get("MolecularWeight"),
                    "canonical_smiles": props.get("CanonicalSMILES"),
                    "isomeric_smiles": props.get("IsomericSMILES"),
                    "inchi": props.get("InChI"),
                    "inchi_key": props.get("InChIKey"),
                    "exact_mass": props.get("ExactMass"),
                    "depiction_2d": {
                        "png_url": pubchem_cid_png_url(best_cid, image_size=image_size),
                        "image_size": image_size,
                    },
                    "synonyms": [],
                }

                try:
                    best["synonyms"] = pubchem_cid_synonyms(session, best_cid, top_n=synonyms_top_n)
                except requests.HTTPError as e:
                    best["synonyms_error"] = f"http_{getattr(e.response, 'status_code', None)}"

                if save_images:
                    out_path = os.path.join(image_dir, f"CID{best_cid}.png")
                    try:
                        download_png(session, best["depiction_2d"]["png_url"], out_path)
                        best["depiction_2d"]["local_path"] = out_path
                    except Exception as e:
                        best["depiction_2d"]["download_error"] = str(e)

                entry["best"] = best
                compounds.append(entry)
                compounds_resolved += 1

            except Exception as e:
                entry["error"] = str(e)
                compounds.append(entry)

            if sleep_s and sleep_s > 0:
                time.sleep(sleep_s)

        payload = {
            "meta": {
                "source": "pubchem",
                "retrieved_at": _now_ts(),
                "matched_from": "bdpm.compo_sa_substances|metadata.medicine_details.substances_actives",
                "strategy": "name_to_cid_best_first",
            },
            "compounds": compounds,
            "quality": {
                "parser_version": "pubchem_v1",
                "errors": [],
            },
        }

        try:
            existing_pubchem = (doc.get("sources") or {}).get("pubchem")

            new_has_best = any(
                isinstance(c, dict) and isinstance(c.get("best"), dict) and c["best"].get("cid")
                for c in compounds
            )

            old_has_best = _has_any_best(existing_pubchem)

            if old_has_best and not new_has_best:
                # Évite d'écraser un succès par un échec
                continue

            res = medicines.update_one(
                {"_id": doc_id},
                {"$set": {"sources.pubchem": payload}},
                upsert=False,
            )
            if res.modified_count:
                updated_docs += 1
        except Exception as e:
            errors.append(f"{url or doc_id}: {e}")

    return {
        "scanned": scanned,
        "docs_with_sa": docs_with_sa,
        "compounds_resolved": compounds_resolved,
        "updated": updated_docs,
        "errors": errors[:20],
    }


# ============================
# V3: Enrichissement SUBSTANCES (full PubChem record, chunké)
# ============================

def pubchem_cid_pug_view_record(session: requests.Session, cid: int) -> Dict[str, Any]:
    """
    Récupère le record complet PubChem via PUG View.
    Attention: peut être gros -> on le stocke chunké.
    """
    url = f"{PUBCHEM_BASE.replace('/rest/pug', '')}/rest/pug_view/data/compound/{cid}/JSON"
    # PUBCHEM_BASE est "https://pubchem.ncbi.nlm.nih.gov/rest/pug" dans ton fichier
    # donc on enlève "/rest/pug" pour construire "/rest/pug_view"
    return _get_json(session, url)


def _walk_pubchem_sections(data: Any, path: str = "") -> List[Dict[str, Any]]:
    """
    Découpe un record PUG View en "sections" stockables.
    On parcourt récursivement les clés; dès qu'on trouve une liste "Section", on split.
    """
    out: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        # Si on trouve la structure standard PUG View
        if "Section" in data and isinstance(data["Section"], list):
            for i, sec in enumerate(data["Section"]):
                sec_path = f"{path}/Section[{i}]"
                out.append({"section_path": sec_path, "payload": sec})
                # et on continue à descendre pour multiplier le découpage
                out.extend(_walk_pubchem_sections(sec, sec_path))
            return out

        # Sinon on descend dans toutes les clés
        for k, v in data.items():
            child_path = f"{path}/{k}" if path else k
            out.extend(_walk_pubchem_sections(v, child_path))

    elif isinstance(data, list):
        for i, item in enumerate(data):
            child_path = f"{path}[{i}]"
            out.extend(_walk_pubchem_sections(item, child_path))

    return out


def _extract_brand_like_names_from_synonyms(syns: List[str], *, max_out: int = 50) -> List[str]:
    """
    Heuristique simple:
    - pas de chiffres
    - 2..30 chars
    - caractères lettres/espace/- uniquement
    - on remonte en UPPER pour homogénéiser
    """
    out: List[str] = []
    seen = set()

    for s in syns or []:
        if not isinstance(s, str):
            continue
        x = _normalize_spaces(s)
        if not x:
            continue
        if any(ch.isdigit() for ch in x):
            continue
        if len(x) < 2 or len(x) > 30:
            continue
        if not re.fullmatch(r"[A-Za-zÀ-ÿ\-\s']+", x):
            continue
        u = _ascii_fold(x).upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= max_out:
            break

    return out

def pubchem_download_2d_png(session: requests.Session, cid: int, out_dir: str) -> str:
    """
    Télécharge l'image 2D PNG depuis PubChem et retourne le chemin local.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(out_dir) / f"cid_{cid}_2d.png")


    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG"
    r = session.get(url, params={"record_type": "2d", "image_size": "large"}, timeout=30)
    r.raise_for_status()

    with open(out_path, "wb") as f:
        f.write(r.content)

    return out_path


def _is_serverbusy_503(exc: Exception) -> bool:
    try:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code == 503
    except Exception:
        pass
    return "PUGREST.ServerBusy" in str(exc) or "503" in str(exc)


def _retry_with_backoff(fn, *, max_attempts: int = 6, base_sleep: float = 1.0):
    """
    Retry simple avec backoff exponentiel + jitter pour PubChem (503 ServerBusy).
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if not _is_serverbusy_503(e):
                raise
            # backoff exponentiel + jitter
            sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            print(f"[PubChem] 503 ServerBusy -> retry {attempt}/{max_attempts} in {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise last_exc



def enrich_substances_with_pubchem_full(
    *,
    collection_name: str = "substances",
    limit_docs: Optional[int] = None,
    sleep_s: float = 0.2,
    synonyms_top_n: int = 200,
    store_full_record: bool = True,
    full_sections_collection: str = "pubchem_compound_sections",
    download_images: bool = False,
    images_out_dir: str = "data/pubchem_images",
    only_retryable_errors: bool = False,
) -> Dict[str, Any]:
    """
    V3:
    - Parcourt substances_v3 (via get_collection("substances"))
    - Trouve un CID (name -> cids) en utilisant label/label_normalized (et tes règles normalize_sa_for_pubchem)
    - Stocke un résumé dans substances_v3.sources.pubchem
    - Si store_full_record=True: récupère PUG View record complet et le stocke chunké
      dans full_sections_collection (1 doc par section/chunk)
    """
    substances = get_collection(collection_name)
    sections_col = get_collection(full_sections_collection)

    # Index utiles
    substances.create_index("label_normalized")
    substances.create_index("sources.pubchem.cid")
    substances.create_index("sources.pubchem.error")
    substances.create_index("sources.pubchem.retryable")
    sections_col.create_index("cid")
    sections_col.create_index("section_path")

    session = _requests_session()

    # Filtre:
    # - par défaut: on traite ceux jamais traités OU ceux en erreur "cid_lookup_error" (rejouable)
    # - option: only_retryable_errors -> uniquement retryable=True
    if only_retryable_errors:
        query_filter = {"sources.pubchem.retryable": True}
    else:
        query_filter = {
            "$or": [
                {"sources.pubchem": {"$exists": False}},
                {"sources.pubchem.error": {"$regex": "^cid_lookup_error"}},
            ]
        }

    cursor = substances.find(
        query_filter,
        projection={"_id": 1, "label": 1, "label_normalized": 1, "sources.pubchem": 1},
    )

    scanned = 0
    updated = 0
    matched = 0
    no_cid = 0
    stored_full = 0
    images_ok = 0
    images_fail = 0

    errors: List[str] = []

    for sub in cursor:
        scanned += 1
        if limit_docs is not None and scanned > limit_docs:
            break

        sub_id = sub["_id"]
        label = _safe_str(sub.get("label"))
        label_norm = _safe_str(sub.get("label_normalized"))

        # Génère des requêtes candidates (ta logique)
        raw_for_queries = label_norm or label
        queries = normalize_sa_for_pubchem(raw_for_queries)
        if not queries:
            continue

        # 1) Trouver CID
        best_cid: Optional[int] = None
        query_used: Optional[str] = None

        try:
            for q in queries:
                try:
                    cids = _retry_with_backoff(
                        lambda: pubchem_name_to_cids(session, q),
                        max_attempts=6,
                        base_sleep=1.0,
                    )
                except requests.HTTPError as e:
                    # 404 -> pas trouvé pour cette query, on continue
                    if getattr(e.response, "status_code", None) == 404:
                        cids = []
                    else:
                        raise

                if cids:
                    best_cid = int(cids[0])
                    query_used = q
                    break

            # Si aucune query n'a donné de CID => no_cid_found
            if best_cid is None:
                no_cid += 1
                substances.update_one(
                    {"_id": sub_id},
                    {"$set": {"sources.pubchem": {
                        "error": "no_cid_found",
                        "queries": queries[:50],
                        "fetched_at": _now_ts(),
                        "version": "pubchem_v3_full",
                    }}},
                )
                continue

        except Exception as e:
            # Erreur technique (503, timeout, etc.)
            errors.append(f"{sub_id}: cid_lookup_error: {e}")
            retryable = _is_serverbusy_503(e)

            substances.update_one(
                {"_id": sub_id},
                {"$set": {"sources.pubchem": {
                    "error": f"cid_lookup_error: {str(e)}",
                    "retryable": bool(retryable),
                    "queries": queries[:50],
                    "fetched_at": _now_ts(),
                    "version": "pubchem_v3_full",
                }}},
            )
            continue

        matched += 1

        # 2) Résumé léger (props + synonyms)
        summary: Dict[str, Any] = {}
        syns: List[str] = []

        try:
            props = pubchem_cid_properties(session, best_cid)
            summary.update({
                "molecular_formula": props.get("MolecularFormula"),
                "molecular_weight": props.get("MolecularWeight"),
                "canonical_smiles": props.get("CanonicalSMILES"),
                "isomeric_smiles": props.get("IsomericSMILES"),
                "inchi": props.get("InChI"),
                "inchi_key": props.get("InChIKey"),
                "exact_mass": props.get("ExactMass"),
            })
        except Exception as e:
            summary["properties_error"] = str(e)

        try:
            syns = pubchem_cid_synonyms(session, best_cid, top_n=synonyms_top_n)
        except Exception as e:
            summary["synonyms_error"] = str(e)
            syns = []

        brand_like = _extract_brand_like_names_from_synonyms(syns)

        # 3) Image (optionnel) — ne bloque jamais l'enrichissement
        image_path = None
        if download_images:
            try:
                image_path = pubchem_download_2d_png(session, best_cid, images_out_dir)
                images_ok += 1
            except Exception as e:
                summary["image_error"] = str(e)
                images_fail += 1

        # 4) Full record chunké
        sections_count = 0
        if store_full_record:
            try:
                full = pubchem_cid_pug_view_record(session, best_cid)
                chunks = _walk_pubchem_sections(full)

                # Remplace le contenu existant pour ce CID
                sections_col.delete_many({"cid": best_cid})

                ops = []
                for i, ch in enumerate(chunks):
                    doc_id = f"CID|{best_cid}|{i:04d}"
                    ops.append(
                        UpdateOne(
                            {"_id": doc_id},
                            {"$set": {
                                "cid": best_cid,
                                "section_path": ch["section_path"],
                                "payload": ch["payload"],
                                "stored_at": _now_ts(),
                            }},
                            upsert=True,
                        )
                    )

                if ops:
                    sections_col.bulk_write(ops, ordered=False)

                sections_count = len(chunks)
                stored_full += 1

            except Exception as e:
                summary["full_record_error"] = str(e)

        payload = {
            "cid": best_cid,
            "summary": summary,
            "synonyms_top": syns[:50],
            "brand_like_names": brand_like,
            "raw": {
                "stored": bool(store_full_record and sections_count > 0),
                "collection": full_sections_collection,
                "sections_count": sections_count,
            },
            "match": {
                "method": "label_normalized_queries",
                "query_used": query_used,
                "queries": queries[:25],
            },
            "fetched_at": _now_ts(),
            "version": "pubchem_v3_full",
        }

        # Ajoute image seulement si on a un path
        if image_path:
            payload["image"] = {"stored": True, "path": image_path}
        else:
            payload["image"] = {"stored": False, "path": None}

        try:
            res = substances.update_one({"_id": sub_id}, {"$set": {"sources.pubchem": payload}})
            if res.modified_count:
                updated += 1
        except Exception as e:
            errors.append(f"{sub_id}: update_error: {e}")

        if sleep_s and sleep_s > 0:
            time.sleep(sleep_s)

        if scanned % 100 == 0:
            print(
                f"[PubChem V3] scanned={scanned} matched={matched} updated={updated} "
                f"no_cid={no_cid} stored_full={stored_full} images_ok={images_ok} images_fail={images_fail}"
            )

    return {
        "scanned": scanned,
        "matched": matched,
        "updated": updated,
        "no_cid": no_cid,
        "stored_full": stored_full,
        "errors": errors[:20],
        "images_ok": images_ok,
        "images_fail": images_fail,
    }


