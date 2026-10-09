from agents.pack.evaluator import evaluate_pack_box, parse_order_lines
from agents.pack.parser import ImageQuality, ModelObservation, ObservedItem, UnrecognisedItem


def test_perfect_box_seals():
    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-A", count=2, count_confidence=0.95, identity_confidence=0.95),
            ObservedItem(sku="SKU-B", count=1, count_confidence=0.95, identity_confidence=0.95),
        ],
        image_quality=ImageQuality(usable=True),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-A:2;SKU-B:1", obs)
    assert verdict == "SEAL"
    assert action == "go"
    assert set(checks.keys()) == {"items_present", "quantities_correct", "no_extra_items"}
    assert all(c.result == "PASS" for c in checks.values())


def test_missing_item_fails_when_unoccluded():
    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-A", count=1, count_confidence=0.95, identity_confidence=0.95),
        ],
        image_quality=ImageQuality(usable=True),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-A:1;SKU-B:1", obs)
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"
    assert checks["items_present"].result == "FAIL"
    assert checks["items_present"].reason_code == "MISSING_ITEMS"


def test_missing_item_becomes_uncertain_when_occlusion_suspected():
    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-A", count=1, count_confidence=0.95, identity_confidence=0.95),
        ],
        image_quality=ImageQuality(usable=True),
        occlusion_suspected=True,
    )
    checks, verdict, action = evaluate_pack_box("SKU-A:1;SKU-B:1", obs)
    assert verdict == "UNCERTAIN"
    assert action == "STOP"
    assert checks["items_present"].result == "UNCERTAIN"
    assert checks["items_present"].reason_code == "ITEM_OCCLUDED"


def test_low_identity_confidence_yields_uncertain():
    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-A", count=1, count_confidence=0.95, identity_confidence=0.50),
        ],
        image_quality=ImageQuality(usable=True),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-A:1", obs)
    assert verdict == "UNCERTAIN"
    assert checks["items_present"].result == "UNCERTAIN"
    assert checks["items_present"].reason_code == "LOW_IDENTITY_CONFIDENCE"


def test_extra_decoy_item_fails():
    obs = ModelObservation(
        observed_items=[
            ObservedItem(sku="SKU-A", count=1, count_confidence=0.95, identity_confidence=0.95),
            ObservedItem(sku="SKU-DECOY", count=1, count_confidence=0.95, identity_confidence=0.95),
        ],
        image_quality=ImageQuality(usable=True),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-A:1", obs)
    assert verdict == "STOP_AND_FIX"
    assert checks["no_extra_items"].result == "FAIL"
    assert checks["no_extra_items"].reason_code == "DECOY_ITEM_PRESENT"
