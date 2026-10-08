import pytest

from agents.pack.catalogue import (
    build_candidate_skus,
    format_prompt_candidate_list,
    get_org_catalogue,
    register_org_catalogue,
)


def test_tenancy_unknown_org_raises_lookup_error():
    with pytest.raises(LookupError):
        get_org_catalogue("org_evil_intruder")


def test_valid_org_returns_isolated_catalogue():
    alpha = get_org_catalogue("org_demo_alpha")
    bravo = get_org_catalogue("org_demo_bravo")
    assert "SKU-TOWEL-BLU" in alpha
    assert "SKU-CABLE-USBC" in bravo


def test_build_candidate_skus_merges_order_skus():
    skus = build_candidate_skus("org_demo_alpha", ["SKU-CUSTOM-999"])
    assert "SKU-CUSTOM-999" in skus
    assert "SKU-BOTTLE-750" in skus


def test_format_candidate_list_never_contains_quantities():
    cat = {"SKU-A": {"title": "Widget", "description": "Small red widget"}}
    formatted = format_prompt_candidate_list(["SKU-A"], cat)
    assert "SKU-A: Widget - Small red widget" in formatted
    assert ":" not in formatted.replace("SKU-A: Widget", "")  # No qty:count
