.PHONY: setup demo-l5x sim backend backend-live frontend test test-parser test-backend test-simulator test-frontend gates gate1 gate4 clean

# All Python commands run through the single shared venv at l5x-copilot/.venv
# (parser + backend + simulator all import from it — see each requirements.txt).
PY := ./l5x-copilot/.venv/bin/python
PIP := ./l5x-copilot/.venv/bin/pip

# Mock mode by default so `make backend` works with zero API key.
# `make backend-live` runs real Claude on the local Claude Code subscription
# (Agent SDK, no API key); `make backend ASKPLC_MOCK=0` uses ANTHROPIC_API_KEY.
ASKPLC_MOCK ?= 1

## setup -- create the venv, install parser + backend + simulator deps, npm install the frontend
## (the parser package is never `pip install`ed -- plc_tools.py / gate scripts put
## l5x-copilot/ on sys.path directly -- so this just installs its runtime deps.)
setup:
	python3 -m venv l5x-copilot/.venv
	$(PIP) install --upgrade pip
	$(PIP) install lxml rich pytest pytest-cov
	$(PIP) install -r app/backend/requirements.txt
	$(PIP) install -r app/simulator/requirements.txt
	cd app/frontend && npm install
	@echo "Setup complete. Copy .env.example to .env to configure ANTHROPIC_API_KEY / ASKPLC_MODEL."

## demo-l5x -- regenerate the PressLine_3 demo program from its YAML spec and verify the diagnostic chain
demo-l5x:
	cd demo_cell && ../$(PY) generate_l5x.py
	cd demo_cell && ../$(PY) verify_scenario.py

## sim -- run the PressLine_3 live simulator (OPC UA :4840, chaos/status HTTP :8090)
sim:
	$(PY) -m app.simulator --port 4840 --http-port 8090

## backend -- run the FastAPI chat backend (mock mode by default; port 8000)
backend:
	ASKPLC_MOCK=$(ASKPLC_MOCK) $(PY) -m uvicorn app.backend.server:app --port 8000

## backend-live -- real Claude via the local Claude Code login (subscription; no API key)
backend-live:
	ASKPLC_MOCK=0 ASKPLC_PROVIDER=subscription $(PY) -m uvicorn app.backend.server:app --port 8000

## frontend -- run the Vite dev server (proxies /api to the backend on :8000)
frontend:
	cd app/frontend && npm run dev

## test -- run every test suite (parser, backend, simulator, frontend unit)
test: test-parser test-backend test-simulator test-frontend

test-parser:
	cd l5x-copilot && ../l5x-copilot/.venv/bin/python -m pytest tests -q --l5x-file ../demo_cell/build/PressLine_3.L5X

test-backend:
	$(PY) -m pytest app/backend/tests -q

test-simulator:
	$(PY) -m pytest app/simulator/tests -q

test-frontend:
	cd app/frontend && npm run build && npm test -- --run

## gates -- the two end-to-end regression gates (static diagnosis + live OPC UA)
gates: gate1 gate4

gate1:
	$(PY) demo_cell/gate1_diagnosis_smoke.py

gate4:
	$(PY) -m app.simulator.gate4_live_smoke

clean:
	find . -name '__pycache__' -not -path '*/node_modules/*' -exec rm -rf {} +
	rm -rf app/frontend/dist
