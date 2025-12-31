# scrapers/utils/sections_tree.py
from __future__ import annotations

from typing import Dict, List, Any, Tuple


def _split_title_and_body(section_text: str) -> Tuple[str, List[str]]:
    lines = [l.strip() for l in section_text.splitlines() if l.strip()]
    if not lines:
        return ("", [])
    title = lines[0]
    body = lines[1:] if len(lines) > 1 else []
    return title, body


def _block(text: str) -> Dict[str, Any]:
    return {
        "text": text,
        "style": {"bold": False, "italic": False, "underline": False, "align": "left"},
    }


def _content_item(text: str) -> Dict[str, Any]:
    return {
        "text": text,
        "formatting": {
            "bold": False,
            "italic": False,
            "underline": False,
            "list_type": None,
            "alignment": "left",
        },
    }


from __future__ import annotations
from typing import Dict, List, Any, Tuple


def _split_title_and_body(section_text: str) -> Tuple[str, str]:
    lines = [l.rstrip() for l in (section_text or "").splitlines()]
    # supprime lignes vides en trop mais garde la structure
    lines = [l for l in lines if l.strip() != ""]
    if not lines:
        return ("", "")
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return title, body


def _block_single(text: str) -> Dict[str, Any]:
    return {
        "text": text,
        "style": {"bold": False, "italic": False, "underline": False, "align": "left"},
    }


def _content_single(text: str) -> Dict[str, Any]:
    return {
        "text": text,
        "formatting": {
            "bold": False,
            "italic": False,
            "underline": False,
            "list_type": None,
            "alignment": "left",
        },
    }


def build_sections_tree(rcp_sections: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Format v2, mais en mode "1 bloc par section" :
    - Root: blocks=[{text:"...tout le texte..."}]
    - Subsection: content=[{text:"...tout le texte..."}]
    """
    def key(num: str):
        return [int(x) for x in num.split(".")]

    ordered = sorted(rcp_sections.items(), key=lambda kv: key(kv[0]))

    roots: List[Dict[str, Any]] = []
    index: Dict[str, Dict[str, Any]] = {}

    for num, txt in ordered:
        title, body = _split_title_and_body(txt)

        if "." not in num:
            node: Dict[str, Any] = {
                "title": title,
                "code": num,
                "blocks": [_block_single(body)] if body else [],
                "subsections": [],
            }
            roots.append(node)
            index[num] = node
        else:
            node = {
                "title": title,
                "code": num,
                "content": [_content_single(body)] if body else [],
                "subsections": [],
            }
            index[num] = node

            parent_num = ".".join(num.split(".")[:-1])
            parent = index.get(parent_num)
            if parent:
                parent["subsections"].append(node)
            else:
                roots.append(node)

    return roots
