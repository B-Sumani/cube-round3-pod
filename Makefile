.PHONY: setup test e2e run case serve health examples expected cases

# Works on Linux/macOS and on Windows (Git Bash / GNU make). Windows without make: use .\pod.ps1 <target>.
ifeq ($(OS),Windows_NT)
  PYTHON ?= py -3
  VENV_BIN := .venv/Scripts
else
  PYTHON ?= python3
  VENV_BIN := .venv/bin
endif
PY := $(VENV_BIN)/python

setup:            ## create .venv and install dependencies
	$(PYTHON) -m venv .venv && $(PY) -m pip install -r requirements.txt
	@$(PY) -c "import os, shutil; os.path.exists('.env') or shutil.copy('.env.example', '.env')"

test:             ## all tests: contracts, hand-offs, workflow state, UNCERTAIN, failures, overrides, e2e, HTTP, examples
	$(PY) -m pytest

e2e:              ## just the end-to-end tests
	$(PY) -m pytest tests/e2e

run: export LOG_LEVEL = WARNING
run:              ## run every sample workflow; state -> out/workflows/*.json, evidence -> out/evidence/*.json
	$(PY) -m orchestration.run --all

case:             ## one workflow, full JSON:  make case UNIT=UNIT-0014 ORG=org_demo_alpha
	@$(PY) -m orchestration.run --unit $(UNIT) --org $(ORG)

serve:            ## orchestrator API on :8100  (POST /workflows, GET /workflows/{id}, GET /health)
	$(PY) -m uvicorn orchestration.api:app --port 8100

health:           ## health of the orchestrator and every agent
	curl -s localhost:8100/health | $(PY) -m json.tool

cases:            ## rebuild data/sample/cases.json from the sample CSVs
	$(PY) scripts/build_sample_cases.py

expected:         ## rebuild data/expected/ (golden outcomes for the organiser STUBS + standard flow)
	$(PY) scripts/build_expected.py

examples:         ## regenerate examples/ from real runs of the stubs
	$(PY) scripts/make_examples.py
