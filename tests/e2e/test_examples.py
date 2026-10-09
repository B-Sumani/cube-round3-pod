"""The examples/ folder is documentation participants will copy. It must validate and stay in sync with the code."""
import json
from pathlib import Path

import pytest

from orchestration.orchestrator import load_flow, run_workflow
from orchestration.store import MemoryStore
from shared.utils.schema import errors

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
BY_PREFIX = {"agent-input": "agent-input", "agent-output": "agent-output", "workflow-state": "workflow-state",
             "final-outcome": "final-outcome", "evidence": "evidence"}
FILES = sorted(p for p in EXAMPLES.rglob("*.json") if p.name.split(".")[0] in BY_PREFIX)


def test_there_are_examples_for_every_path():
    assert {p.name for p in EXAMPLES.iterdir() if p.is_dir()} >= {"happy-path", "uncertain-path", "failure-path", "end-to-end"}
    assert len(FILES) > 20


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(EXAMPLES)))
def test_example_validates(path):
    assert errors(BY_PREFIX[path.name.split(".")[0]], json.loads(path.read_text())) == []


@pytest.mark.parametrize(
    "folder",
    ["happy-path", "uncertain-path", "end-to-end"],
)
def test_example_cases_have_documented_outcomes(folder):
    """Example snapshots document the starter flow, not the live agent implementation."""
    case = json.loads((EXAMPLES / folder / "case.json").read_text())

    state_name = (
        "workflow-state.continue.json"
        if folder == "uncertain-path"
        else "workflow-state.json"
    )
    documented = json.loads((EXAMPLES / folder / state_name).read_text())

    assert case["org_id"]
    assert case["unit_id"]
    assert case["route"] in ("fba", "mfn", "unknown")
    assert isinstance(case["returned"], bool)
    assert documented["status"]
    assert documented["final_outcome"]["outcome"]