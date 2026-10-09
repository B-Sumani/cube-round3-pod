"""Seller catalogue management and candidate SKU preparation.

Enforces:
1. Tenancy: Loads catalogue per org with no cross-org fallback. Raises LookupError for unknown orgs.
2. Candidate restriction: Orders SKUs + decoys from the tenant catalogue.
3. Information hiding: Candidate list formatting NEVER includes order quantities.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional

PACKAGE_DIR = Path(__file__).resolve().parent

# Default known catalogues per demo organisation
DEFAULT_ORG_CATALOGUES: Dict[str, Dict[str, Dict[str, str]]] = {
    "org_demo_alpha": {
        "SKU-BOTTLE-750": {
            "title": "Stainless Steel Water Bottle 750ml",
            "description": "Double-wall insulated metal water bottle with loop cap.",
        },
        "SKU-TOWEL-BLU": {
            "title": "Microfiber Gym Towel Blue",
            "description": "Quick-dry blue athletic microfiber towel.",
        },
        "SKU-SERUM-30": {
            "title": "Hyaluronic Acid Facial Serum 30ml",
            "description": "Glass dropper bottle with amber tint and white dropper.",
        },
        "SKU-PUZZLE-500": {
            "title": "500-Piece Jigsaw Puzzle Mountain Lake",
            "description": "Rectangular cardboard puzzle box with alpine scenery illustration.",
        },
        "SKU-SOAP-MYSORE": {
            "title": "Mysore Sandal Soap Carton",
            "description": "Rectangular green carton box with red ornate borders.",
        },
        "SKU-SUNSCREEN-DERMA": {
            "title": "Dermatouch Multivitamin Sunscreen Gel 50g",
            "description": "White squeeze tube with orange accent band.",
        },
        "SKU-SANITIZER-DETTOL": {
            "title": "Dettol Instant Hand Sanitizer 50ml",
            "description": "Clear plastic squeeze bottle with green flip-cap.",
        },
    },
    "org_demo_bravo": {
        "SKU-CABLE-USBC": {
            "title": "Braided USB-C to USB-C Fast Charging Cable 2m",
            "description": "Black nylon braided cable coiled in clear plastic polybag.",
        },
        "SKU-PUZZLE-500": {
            "title": "500-Piece Jigsaw Puzzle Mountain Lake",
            "description": "Rectangular cardboard puzzle box with alpine scenery illustration.",
        },
        "SKU-BOTTLE-750": {
            "title": "Stainless Steel Water Bottle 750ml",
            "description": "Double-wall insulated metal water bottle with loop cap.",
        },
        "SKU-EARBUDS-BOAT": {
            "title": "boAt Airdopes True Wireless Earbuds",
            "description": "Square packaging box with black earbuds graphic.",
        },
        "SKU-BODYMILK-NIVEA": {
            "title": "Nivea Nourishing Body Milk 72h Moisture Lotion",
            "description": "Dark royal blue plastic bottle with white flip-cap.",
        },
        "SKU-TRIMMER-BOMBAY": {
            "title": "Bombay Shaving Company 2-in-1 Trimmer",
            "description": "Teal rectangular box with white branding.",
        },
    },
}

# Runtime org catalogue registry (allows dynamic registration per tenant)
_RUNTIME_CATALOGUES: Dict[str, Dict[str, Dict[str, str]]] = {}


def register_org_catalogue(org_id: str, catalogue: Dict[str, Dict[str, str]]) -> None:
    """Registers or updates a catalogue for a specific organisation."""
    _RUNTIME_CATALOGUES[org_id] = dict(catalogue)


def get_org_catalogue(org_id: str) -> Dict[str, Dict[str, str]]:
    """Returns the product catalogue for the specified organisation.

    Strict Tenancy:
    - Checks runtime registry first, then default demo catalogues.
    - If org_id is not recognised, raises LookupError (which translates to HTTP 404 / AgentRejected).
    - NEVER falls back to another organization's catalogue.
    """
    if not org_id or not isinstance(org_id, str):
        raise LookupError("Missing or invalid org_id")

    if org_id in _RUNTIME_CATALOGUES:
        return _RUNTIME_CATALOGUES[org_id]

    # Check for org-specific CSV under agents/pack/data/<org_id>_catalogue.csv
    custom_csv = PACKAGE_DIR / "data" / f"{org_id}_catalogue.csv"
    if custom_csv.is_file():
        cat = _load_catalogue_csv(custom_csv)
        _RUNTIME_CATALOGUES[org_id] = cat
        return cat

    if org_id in DEFAULT_ORG_CATALOGUES:
        return DEFAULT_ORG_CATALOGUES[org_id]

    raise LookupError(f"No catalogue or authorization for organisation: {org_id}")


def _load_catalogue_csv(path: Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("sku") or "").strip()
            if sku:
                out[sku] = {
                    "title": (row.get("title") or "").strip(),
                    "description": (row.get("description") or "").strip(),
                }
    return out


def build_candidate_skus(org_id: str, order_skus: List[str]) -> List[str]:
    """Builds the restricted candidate SKU list for this unit.

    Merges the tenant's catalogue SKUs with any SKUs present in the order lines.
    Returns a sorted list of unique candidate SKUs.
    """
    cat = get_org_catalogue(org_id)
    candidates = set(cat.keys())
    candidates.update(s.strip() for s in order_skus if s.strip())
    return sorted(candidates)


def format_prompt_candidate_list(
    candidate_skus: List[str], catalogue: Dict[str, Dict[str, str]]
) -> str:
    """Formats the catalogue candidate items for inclusion in the model prompt.

    CRITICAL RULE:
    Order quantities are NEVER included. Only SKU and product details are shown.
    """
    lines: List[str] = []
    for sku in candidate_skus:
        entry = catalogue.get(sku, {})
        title = entry.get("title", "")
        desc = entry.get("description", "")
        if title and desc:
            lines.append(f"- {sku}: {title} - {desc}")
        elif title:
            lines.append(f"- {sku}: {title}")
        else:
            lines.append(f"- {sku}")
    return "\n".join(lines)
