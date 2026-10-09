"""Receiving Manager (Round 2 agent) behind the Pod contract: own fixtures, both perception modes, fail-open, tenancy."""
import json
from pathlib import Path

import pytest

from agents.receiving import app as receiving
from agents.receiving.r2.vision import VisionAnalysisResponse, VisionService
from shared.utils.hashing import verify
from shared.utils.schema import errors
from tests.conftest import make_input

ROOT = Path(__file__).resolve().parents[2]  # repo root
CASES = {c["unit_id"]: c for c in json.loads((ROOT / "data/sample/cases.json").read_text())}


def run(unit, **kw):
    out = receiving.handle(make_input("receiving", CASES[unit], **kw) if not kw.get("request") else kw["request"])
    assert errors("agent-output", out) == [] and verify(out["evidence"])
    return out


def checks(out):
    return {c["check_key"]: c["verdict"] for c in out["evidence"]["checks"]}


# ---------------------------------------------------------------- recorded mode (Round 2 rules, no model)
def test_clean_receipt_passes_with_no_model_call():
    out = run("UNIT-0001")
    assert out["verdict"] == "PASS" and out["evidence"]["decision"]["outcome"] == "accept"
    assert out["evidence"]["model"] == {"name": "receiving-r2-rules", "version": receiving.RULES_VERSION, "provider": None,
                                        "prompt_version": None, "calls": 0, "cost_usd": 0}
    assert out["evidence"]["payload"]["perception"] == "recorded"


def test_round2_rule_checks_units_per_carton_separately():
    """UNIT-0005: 1 carton, 10 per carton counted vs 12 ordered. Round 2 reports both per-carton and total."""
    c = checks(run("UNIT-0005"))
    assert c["units_per_carton"] == "FAIL" and c["quantity"] == "FAIL" and c["carton_damage"] == "FAIL"


def test_identity_mismatch_rejects():
    out = run("UNIT-0007")
    assert checks(out)["identity_match"] == "FAIL" and out["evidence"]["decision"]["outcome"] == "reject"


def test_unconfirmed_identity_is_uncertain_not_pass():
    out = run("UNIT-0029")
    c = next(c for c in out["evidence"]["checks"] if c["check_key"] == "identity_match")
    assert c["verdict"] == "UNCERTAIN" and c["uncertain_reason"] == "insufficient_evidence"
    assert out["verdict"] == "UNCERTAIN" and out["evidence"]["decision"]["needs_human"] is True


def test_shortfall_is_labelled_supplier_side():
    p = run("UNIT-0025")["evidence"]["payload"]
    assert p["shortfall_units"] == 6 and p["shortfall_side"] == "supplier"


def test_inputs_are_content_addressed_and_unit_scope_is_po_line():
    ev = run("UNIT-0001")["evidence"]
    row = next(i for i in ev["inputs"] if i["kind"] == "csv_row")
    assert len(row["sha256"]) == 64 and row["ref"].endswith("#RCV-0001")
    assert ev["subject"]["unit_scope"] == "po_line" and ev["subject"]["refs"]["po_number"] == "PO-7000"


def test_components_are_not_reported_without_observations():
    ev = run("UNIT-0002")["evidence"]
    assert "components" not in checks({"evidence": ev})
    assert ev["payload"]["checks_not_performed"]


def test_po_inconsistent_quantity_is_uncertain():
    row = receiving.sample_data.row("receiving", "UNIT-0001", "org_demo_alpha")
    po = receiving.purchase_order({**row, "qty_ordered": "25"})  # 1 x 24 != 25
    c, _ = receiving.recorded_checks(row, po, [])
    assert next(x for x in c if x["check_key"] == "quantity")["verdict"] == "UNCERTAIN"


def test_wrong_tenant_is_refused():
    with pytest.raises(LookupError):
        receiving.handle(make_input("receiving", {**CASES["UNIT-0001"], "org_id": "org_demo_bravo"}))


def test_same_request_same_record_id_and_new_run_new_id():
    req = make_input("receiving", CASES["UNIT-0001"])
    a, b = receiving.handle(req), receiving.handle(req)
    c = receiving.handle({**req, "request_id": req["request_id"] + ":r2"})
    assert a["evidence"]["record_id"] == b["evidence"]["record_id"] != c["evidence"]["record_id"]


# ---------------------------------------------------------------- vision mode (one batched call, mocked)
@pytest.fixture
def captures(tmp_path, monkeypatch):
    folder = tmp_path / "UNIT-0001" / "receiving"
    folder.mkdir(parents=True)
    for view in ("pallet", "carton"):
        (folder / f"UNIT-0001_{view}.jpg").write_bytes(b"\xff\xd8\xff" + view.encode())
    monkeypatch.setenv("INPUT_DIR", str(tmp_path))
    monkeypatch.setenv("RECEIVING_VISION", "on")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    from orchestration.orchestrator import discover_inputs
    return discover_inputs("UNIT-0001", "receiving")


def fake_model(readings_by_image, calls):
    def _call(self, settings):
        calls.append([i.image_id for i in self.inspection.images])
        self.model_version = "fake-vision-1"
        return VisionAnalysisResponse.model_validate({"images": [
            {"image_id": image_id, "visibility": "clear", "observations": [
                {"check_type": k, "observation": v, "confidence": 0.95, "description": "fixture"} for k, v in obs]}
            for image_id, obs in readings_by_image.items()]})
    return _call


def test_vision_mode_makes_one_batched_call_and_rules_decide(captures, monkeypatch):
    refs = [i["ref"] for i in captures]
    clean = [("sku", "SKU-TOWEL-BLU"), ("carton", 1), ("units_per_carton", 24), ("quantity", 24),
             ("variant", "bath"), ("damage", "none"), ("components", ["towel"])]
    calls = []
    monkeypatch.setattr(VisionService, "_call_model", fake_model({refs[0]: clean, refs[1]: [("damage", ["crushing"])]}, calls))
    out = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": captures})
    ev = out["evidence"]
    assert len(calls) == 1 and sorted(calls[0]) == sorted(refs)  # one call per unit, all images
    assert ev["model"]["calls"] == 1 and ev["model"]["name"] != "receiving-r2-rules" and ev["payload"]["perception"] == "vision"
    c = checks(out)
    assert c["identity_match"] == c["quantity"] == c["components"] == "PASS"
    assert c["carton_damage"] == "FAIL" and out["verdict"] == "FAIL"  # damage seen on the second photo only
    damage = next(x for x in ev["checks"] if x["check_key"] == "carton_damage")
    assert refs[1] in damage["evidence_refs"]
    assert {i["sha256"] for i in ev["inputs"] if i["kind"] == "image"} == {i["sha256"] for i in captures}


def test_vision_mode_photos_disagree_is_uncertain(captures, monkeypatch):
    refs = [i["ref"] for i in captures]
    monkeypatch.setattr(VisionService, "_call_model",
                        fake_model({refs[0]: [("sku", "SKU-TOWEL-BLU")], refs[1]: [("sku", "SKU-OTHER")]}, []))
    out = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": captures})
    c = next(x for x in out["evidence"]["checks"] if x["check_key"] == "identity_match")
    assert c["verdict"] == "UNCERTAIN" and c["uncertain_reason"] == "conflicting_evidence"


def test_model_error_fails_open_as_pending(captures, monkeypatch):
    def boom(self, settings):
        raise TimeoutError("model timed out")
    monkeypatch.setattr(VisionService, "_call_model", boom)
    out = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": captures})
    assert out["status"] == "pending" and out["verdict"] == "UNCERTAIN" and out["error"]["code"] == "model_error"
    assert out["evidence"]["checks"] == []  # no invented judgment


def test_model_inventing_an_image_id_fails_open(captures, monkeypatch):
    monkeypatch.setattr(VisionService, "_call_model", fake_model({"made-up.jpg": [("sku", "X")]}, []))
    out = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": captures})
    assert out["status"] == "pending" and "unknown image_id" in out["error"]["message"]


def test_input_ref_cannot_escape_the_input_root(captures, monkeypatch):
    monkeypatch.setattr(VisionService, "_call_model", fake_model({}, []))
    bad = [{"ref": "../../secret.jpg", "kind": "image", "sha256": None}]
    out = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": bad})
    assert out["status"] == "pending" and "escapes" in out["error"]["message"]


def test_vision_off_with_captures_uses_recorded_mode_and_keeps_capture_hashes(captures, monkeypatch):
    monkeypatch.setenv("RECEIVING_VISION", "off")
    ev = run("UNIT-0001", request=make_input("receiving", CASES["UNIT-0001"]) | {"inputs": captures})["evidence"]
    assert ev["payload"]["perception"] == "recorded" and ev["model"]["calls"] == 0
    assert all(i["sha256"] for i in ev["inputs"])


def test_row_ref_names_the_data_dir_actually_used(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(ROOT / "data/pod"))
    ev = receiving.handle(make_input("receiving", CASES["UNIT-0001"]))["evidence"]
    assert next(i for i in ev["inputs"] if i["kind"] == "csv_row")["ref"] == "data/pod/receiving_sample.csv#RCV-0001"
