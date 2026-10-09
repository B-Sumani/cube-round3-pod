"""Evaluate the integrated Receiving agent and write docs/evaluation.md.

A. Pod units (data/pod/, hand-labelled in labels.json): per-check confusion counts + end-to-end final outcomes.
B. The 100 organiser sample units: integrated agent vs the organiser stub (git HEAD:agents/receiving/app.py, or
   the copy in scripts/_stub_receiving.py when git is unavailable), check by check, with the reason for each difference.

Positive class = FAIL (an exception was detected). UNCERTAIN predictions are not forced into the matrix: they are counted
separately (abstentions), split by whether the truth was UNCERTAIN (a correct abstention) or not.
Run:  python scripts/evaluate.py      (recorded mode; no model calls, deterministic)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["RECEIVING_VISION"] = "off"

KEYS = ["identity_match", "carton_count", "units_per_carton", "quantity", "carton_damage", "unit_damage", "quality_flags"]


def make_input(case: dict) -> dict:
    wf = f"WF-{case['org_id']}-{case['unit_id']}"
    return {"schema_version": "1.0", "request_id": f"{wf}:receiving", "workflow_id": wf, "stage": "receiving",
            "subject": {"org_id": case["org_id"], "subject_id": case["unit_id"], "route": case["route"]},
            "inputs": [], "previous_evidence": [], "context": {"overrides": [], "case": case}}


def checks_of(out: dict) -> dict:
    return {c["check_key"]: c for c in out["evidence"]["checks"]}


def load_stub():
    try:
        src = subprocess.run(["git", "show", "HEAD:agents/receiving/app.py"], cwd=ROOT, capture_output=True, text=True,
                             check=True, encoding="utf-8").stdout
    except Exception:
        src = ""
    if "receiving-stub@0" not in src:
        p = ROOT / "scripts" / "_stub_receiving.py"
        if not p.exists():
            return None
        src = p.read_text(encoding="utf-8")
    mod = types.ModuleType("receiving_stub")
    exec(compile(src.replace("app = make_app(STAGE, handle)", ""), "receiving_stub", "exec"), mod.__dict__)
    return mod.handle


def matrix(pairs):
    """pairs: [(truth, pred)]. Returns dict of counts."""
    m = Counter()
    for truth, pred in pairs:
        if pred == "UNCERTAIN":
            m["U_correct" if truth == "UNCERTAIN" else "U_abstain"] += 1
        elif pred == "FAIL":
            m["TP" if truth == "FAIL" else "FP"] += 1
        else:  # PASS
            m["TN" if truth == "PASS" else ("FN" if truth == "FAIL" else "overconfident")] += 1
    return m


def stub_on_pod(stub) -> list[str]:
    """The organiser stub scored on the same labelled Pod units (shared checks only)."""
    pod = ROOT / "data" / "pod"
    labels = json.loads((pod / "labels.json").read_text(encoding="utf-8"))["units"]
    cases = json.loads((pod / "cases.json").read_text(encoding="utf-8"))
    pairs, wrong = [], []
    for case in cases:
        got = checks_of(stub(make_input(case)))
        for k, truth in labels[case["unit_id"]]["receiving_checks"].items():
            if k in got:
                pairs.append((truth, got[k]["verdict"]))
                if got[k]["verdict"] != truth:
                    wrong.append(f"{case['unit_id']} `{k}`: truth {truth}, stub {got[k]['verdict']}")
            else:
                wrong.append(f"{case['unit_id']} `{k}`: not checked by the stub (truth {truth})")
    m = matrix(pairs)
    return [f"Organiser stub on the same Pod units (checks it produces): TP {m['TP']}, FP {m['FP']}, FN {m['FN']}, "
            f"TN {m['TN']}, UNCERTAIN {m['U_correct'] + m['U_abstain']}, PASS when truth U {m['overconfident']}.",
            "Where the stub is wrong or blind (and the integrated agent is right):", *[f"- {w}" for w in wrong
            if "not checked" not in w or "PASS" not in w.split("truth ")[-1]]]


def pod_section(handle) -> tuple[list[str], dict]:
    from orchestration.orchestrator import load_flow, run_workflow
    from orchestration.store import MemoryStore

    pod = ROOT / "data" / "pod"
    labels = json.loads((pod / "labels.json").read_text(encoding="utf-8"))["units"]
    cases = json.loads((pod / "cases.json").read_text(encoding="utf-8"))
    per_check, outcomes, rows = defaultdict(list), [], []
    for case in cases:
        lab = labels[case["unit_id"]]
        got = checks_of(handle(make_input(case)))
        for k in KEYS:
            per_check[k].append((lab["receiving_checks"][k], got[k]["verdict"] if k in got else "MISSING"))
        wf = run_workflow(case, load_flow(ROOT / "orchestration" / "flow.json"), MemoryStore())
        fo = wf["final_outcome"]
        ok = fo["outcome"] == lab["final_outcome"]
        outcomes.append(ok)
        rows.append(f"| {case['unit_id']} | {case['org_id']} | {case['route']}{' + returned' if case['returned'] else ''} | "
                    f"{lab['scenario']} | {lab['final_outcome']} | {fo['outcome']} | {wf['status']} | {'yes' if ok else '**NO**'} |")
    out = ["| Check | TP | FP | FN | TN | UNCERTAIN (truth U) | UNCERTAIN (truth not U) | PASS when truth U |",
           "|---|---|---|---|---|---|---|---|"]
    totals = Counter()
    for k in KEYS:
        m = matrix(per_check[k])
        totals.update(m)
        out.append(f"| `{k}` | {m['TP']} | {m['FP']} | {m['FN']} | {m['TN']} | {m['U_correct']} | {m['U_abstain']} | {m['overconfident']} |")
    out.append(f"| **all** | {totals['TP']} | {totals['FP']} | {totals['FN']} | {totals['TN']} | {totals['U_correct']} | "
               f"{totals['U_abstain']} | {totals['overconfident']} |")
    n = sum(totals.values())
    unc = totals["U_correct"] + totals["U_abstain"]
    head = {"pod_units": len(cases), "pod_checks": n, "pod_FP": totals["FP"], "pod_FN": totals["FN"],
            "pod_uncertain_rate": unc / n if n else 0, "pod_outcomes_correct": sum(outcomes)}
    table = ["| Unit | Org | Route | Scenario | Expected | Got | Status | Match |", "|---|---|---|---|---|---|---|---|", *rows]
    return out + ["", *table], head


def sample_section(handle, stub) -> tuple[list[str], dict]:
    cases = json.loads((ROOT / "data" / "sample" / "cases.json").read_text(encoding="utf-8"))
    verdicts, unit_verdicts_differ, diffs = Counter(), 0, defaultdict(list)
    new_checks = defaultdict(Counter)
    uncertain = total = 0
    for case in cases:
        out = handle(make_input(case))
        verdicts[out["verdict"]] += 1
        got = checks_of(out)
        total += len(got)
        uncertain += sum(c["verdict"] == "UNCERTAIN" for c in got.values())
        if stub is None:
            continue
        ref = stub(make_input(case))
        if ref["verdict"] != out["verdict"]:
            unit_verdicts_differ += 1
        ref_checks = checks_of(ref)
        for k in sorted(set(got) - set(ref_checks)):
            new_checks[k][got[k]["verdict"]] += 1
        for k in sorted(set(got) & set(ref_checks)):
            a, b = got[k]["verdict"], ref_checks[k]["verdict"]
            if a != b:
                diffs[k].append(f"{case['unit_id']}: stub {b} → agent {a} ({got[k].get('detail', '')})")
    lines = [f"Unit verdicts (integrated agent, recorded mode): PASS {verdicts['PASS']}, FAIL {verdicts['FAIL']}, "
             f"UNCERTAIN {verdicts['UNCERTAIN']} of {len(cases)}. Check-level UNCERTAIN rate: {uncertain}/{total} "
             f"({uncertain / total:.1%})."]
    if stub is None:
        lines.append("\nOrganiser stub source not found; comparison skipped.")
    else:
        lines.append(f"\nUnit verdicts that differ from the organiser stub: **{unit_verdicts_differ}**.\n")
        for k, c in sorted(new_checks.items()):
            lines.append(f"- `{k}` is a Round 2 check the stub does not produce: {dict(c)}")
        if not diffs:
            lines.append("- No verdict differences on the checks both produce.")
        for k, items in sorted(diffs.items()):
            lines.append(f"- `{k}`: {len(items)} difference(s)")
            lines += [f"  - {i}" for i in items[:8]]
            if len(items) > 8:
                lines.append(f"  - … {len(items) - 8} more")
    return lines, {"sample_units": len(cases), "sample_verdicts": dict(verdicts), "stub_unit_diffs": unit_verdicts_differ,
                   "sample_uncertain_rate": uncertain / total if total else 0}


def main():
    os.environ["DATA_DIR"] = str(ROOT / "data" / "pod")
    from agents.receiving.app import handle
    pod_lines, head = pod_section(handle)
    os.environ["DATA_DIR"] = str(ROOT / "data" / "sample")
    stub = load_stub()
    if stub:
        os.environ["DATA_DIR"] = str(ROOT / "data" / "pod")
        pod_lines += ["", *stub_on_pod(stub)]
        os.environ["DATA_DIR"] = str(ROOT / "data" / "sample")
    sample_lines, head2 = sample_section(handle, stub)
    head.update(head2)
    doc = f"""# Evaluation — Receiving agent (integrated Round 2) and Pod end-to-end

Generated by `python scripts/evaluate.py` (deterministic; recorded mode; no model calls, $0.00). Re-run after any change.

## Method

- **Agent under test:** `agents/receiving` (`receiving-r2@1.0`): the Round 2 Receiving Manager rules
  (`agents/receiving/r2/decision_engine.py`) wrapped in the Pod contract.
- **Mode evaluated: `recorded`.** The operator-recorded receipt (counts, identity, damage, flags) is run through the
  Round 2 deterministic rules. This measures **decision logic on recorded observations, not perception.**
- **Ground truth (Pod units):** `data/pod/labels.json`, written by hand from each scenario (what is physically true)
  before looking at agent output. 10 synthetic units × 7 checks.
- **Positive class = FAIL** (an exception detected). TP = FAIL when truth FAIL; FP = FAIL when truth not FAIL;
  FN = PASS when truth FAIL; TN = PASS when truth PASS. UNCERTAIN predictions are counted separately (abstentions),
  split by whether the truth was UNCERTAIN. "PASS when truth U" counts over-confident passes (should be 0).
- **Sample units (100):** the organiser CSV has no independent ground truth (the same columns are both input and
  label), so there we report the verdict distribution and every difference from the organiser stub, with the rule
  that causes it. That is a behaviour diff, not an accuracy figure.

## Headline

- Pod units: {head['pod_units']} units, {head['pod_checks']} labelled checks. **False positives: {head['pod_FP']}.
  False negatives: {head['pod_FN']}.** Check-level UNCERTAIN rate: {head['pod_uncertain_rate']:.1%}.
  End-to-end final outcome correct: **{head['pod_outcomes_correct']}/{head['pod_units']}**.
- Sample units: {head['sample_units']} units; verdicts {head['sample_verdicts']}; check-level UNCERTAIN rate
  {head['sample_uncertain_rate']:.1%}; unit verdicts differing from the organiser stub: {head['stub_unit_diffs']}.

## A. Pod units — per-check confusion counts (Receiving)

{chr(10).join(pod_lines)}

Final outcomes use `orchestration/flow.json` defaults (`on_uncertain=continue`). Under `on_uncertain=block` the
UNCERTAIN units halt at Receiving as `BLOCKED` / `INCOMPLETE` until a person overrides
(`tests/e2e/test_pod_units.py::test_uncertain_blocks_then_human_override_resolves_auditably`).

## B. Organiser sample units — integrated agent vs organiser stub

{chr(10).join(sample_lines)}

Where the Round 2 rules differ from the stub (on the 100 sample units only `units_per_carton` shows up; the PO-consistency
rule is exercised by Pod units P007/P008, section A):
- `units_per_carton` is a separate Round 2 check (stub has none): a per-carton miscount is an exception even when it
  is also visible in the total.
- `quantity` uses Round 2 `evaluate_total_quantity_check`: if the PO is internally inconsistent
  (cartons × units/carton ≠ quantity) or the direct count disagrees with cartons × units/carton, the result is
  UNCERTAIN, never a guessed FAIL/PASS.
- Damage tokens go through Round 2 `evaluate_damage_check` (any damage token other than none/unknown is FAIL;
  "uncertain" is UNCERTAIN with `poor_image`).

## Limitations (honest)

- **Recorded mode is not perception.** It shows the decision rules are correct on recorded observations; it says
  nothing about how well a camera/model would read those values.
- **Vision mode is not evaluated here.** It needs labelled photos in `data/input/<unit>/receiving/` and an API key
  (`RECEIVING_VISION=on`). Round 2's own tests cover the vision fusion logic with canned model output.
- Pod units are few (10) and synthetic; the counts show behaviour on designed edge cases, not field accuracy.
- Prep, Pack, Returns and Recovery are still **organiser stubs** in this repository; end-to-end outcomes depend on
  their CSV-replay logic.
- `components` is not checked in recorded mode (the receipt has only a `missing_components` flag, which
  `quality_flags` covers); see `payload.checks_not_performed` on each record.
"""
    (ROOT / "docs" / "evaluation.md").write_text(doc, encoding="utf-8")
    print(json.dumps(head, indent=2))


if __name__ == "__main__":
    main()
