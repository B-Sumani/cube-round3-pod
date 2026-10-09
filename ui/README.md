# CUBE

A unified platform for the complete commerce operations workflow (Receiving, Prep/Pack, Returns, Recovery, and Final Commerce Outcome).

Built with **React + Vite + Tailwind CSS** following the **Wellnessty** signature design system: alternating full-width color bands, hard offset shadows, ink borders, Young Serif typography, and high-contrast accessible states.

> **Brand Name Configuration**: The brand name is configured in one central location: [`ui/src/config/brand.js`](file:///c:/Users/user/Desktop/cube-round3-pod/ui/src/config/brand.js) exporting `BRAND_NAME`. All components, navigation headers, page descriptions, footers, and HTML titles read dynamically from this constant.

---

## Design System & Tokens

Defined in `src/styles/tokens.css` and mapped into `tailwind.config.js`:

- **Page & Header Band (`--cream`)**: `#FFF6DE`
- **Stage Timeline Band (`--teal`)**: `#8ED5CF`
- **Commerce Outcome Band (`--peach`)**: `#FFCDB3`
- **Audit & Evidence Trace Band (`--charcoal`)**: `#3A3A3A` (uses `#FFF6DE` text and `#FFCDB3` cards)
- **Primary Accent & CTAs (`--mustard`)**: `#F8C94D`
- **Text & Borders (`--ink`)**: `#1F1B16`
- **Secondary Muted Text (`--muted`)**: `#5E5A52`
- **Card Surface (`--card`)**: `#FFFDF6`

### Functional Verdict Colors
Always paired with an icon and explicit text label:
- **PASS**: `#2E9E6B` (`CheckCircle2` icon)
- **FAIL**: `#D64545` (`XCircle` icon)
- **UNCERTAIN**: `#E39A0B` (`AlertTriangle` icon)

### Signature Style
- **Cards**: `2px solid #1F1B16`, `14px` border radius, hard offset shadow `4px 4px 0 #1F1B16` (no blur).
- **Buttons**: Rounded `12px`, `2px solid #1F1B16`, primary mustard fill `#F8C94D`, hover lift `-1px` with `5px 5px 0` shadow.
- **Typography**: Headings in *Young Serif* (fallback *DM Serif Display*, *Georgia*), Body and UI in *DM Sans* (fallback *Inter*, *system-ui*).
- **Naming Rule**: The platform name reads from `BRAND_NAME`. No taglines appear anywhere in the UI.

---

## Architecture & Honesty Rules

- **No Authentication**: There is no sign-in. The organisation switch only selects org_id for requests; it is not authentication. Tenant isolation is enforced by org_id in the orchestrator.
- **Continuous Organisation Switcher**: An organisation switch is located in the top bar across all pages. Operators can toggle between `org_demo_alpha` and `org_demo_bravo` at any time. Switching organisations immediately clears all displayed session data (workflows, stage results, evidence, and review queues) to guarantee tenant isolation.
- **Operator Name**: An editable operator name field sits next to the organisation switch in the top bar (defaults to "Operator", saved in `sessionStorage`). The Review Queue automatically prefills the override `actor` from this value.
- **Workflow-Level Execution**: The orchestrator executes whole workflows, not single stages. On an agent's page, running a check invokes the pipeline for that unit, but the view isolates and renders only that stage's result and evidence.
- **Preview-Only Visuals**: The orchestrator holds image captures for units internally; there is no image-upload endpoint in the API. File inputs are for operator preview only and prominently labeled as such.
- **Authoritative Statuses & Outcomes**:
  - Official statuses: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `BLOCKED`, `RECOVERY_REQUIRED` ([orchestration/domain.py:16-24](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/domain.py#L16-L24)).
  - Official final outcomes: `CLEAN`, `EXCEPTION`, `CLAIM_RECOMMENDED`, `NEEDS_REVIEW`, `INCOMPLETE` ([orchestration/domain.py:27-35](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/domain.py#L27-L35)).
- **UNCERTAIN Verdict**: An `UNCERTAIN` verdict is not a low-confidence `PASS`; when evidence is insufficient or occluded, the workflow halts with `needs_human: true` / `BLOCKED`, directing the unit to the Review Queue.

---

## API Architecture & Citations

The UI connects exclusively to the orchestrator HTTP API (`orchestration/api.py`) on port `8100` via Vite's local dev proxy (`/api` -> `http://localhost:8100` in `ui/vite.config.js`). It never calls agents directly and requires no CORS modifications.

| Function | API Endpoint | Source Reference | Description |
|---|---|---|---|
| Execute Case | `POST /workflows` | [orchestration/api.py:42-49](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/api.py#L42-L49) | Dispatches case `{org_id, unit_id, route, returned}` and advances workflow. |
| Workflow State | `GET /workflows/{id}` | [orchestration/api.py:59-62](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/api.py#L59-L62) | Returns authoritative workflow state. |
| Evidence Bundle | `GET /workflows/{id}/evidence` | [orchestration/api.py:64-66](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/api.py#L64-L66) | Returns workflow state plus all stored immutable evidence records. |
| Decision Override | `POST /workflows/{id}/overrides` | [orchestration/api.py:75-82](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/api.py#L75-L82) | Applies a human decision override (`record_id`, `new_verdict`, `actor`, `reason`). |
| Resume Workflow | `POST /workflows/{id}/resume` | [orchestration/api.py:69-72](file:///c:/Users/user/Desktop/cube-round3-pod/orchestration/api.py#L69-L72) | Continues workflow execution after halt, override, or failure. |

---

## Navigation & Top Bar

One consistent top bar appears across every page (Home and application views):
- **LEFT**: Brand logo square + `BRAND_NAME`, immediately followed by links to **Dashboard** and **Review Queue**.
- **RIGHT**: The two-option organisation switch (`org_demo_alpha` / `org_demo_bravo`) with honesty tooltip and the editable **Operator** field.
- **Narrow screens**: Collapses navigation links into a mobile menu button while keeping the brand logo, brand name, and organisation switch visible.
- Agents are not listed in the top bar.

### Routes
1. `/` — **Home Page**:
   - Hero with platform overview and direct links to Dashboard and Agents.
   - **Meet the Agents**: 5 cards in a single row on desktop linking directly to `/app/agents/:stage` (no login).
   - **How it Works**: 5 separate stage cards in sequential order:
     1. **Receiving** (tag: `always`)
     2. **Prep** (tag: `FBA only`)
     3. **Pack** (tag: `MFN only`) — Prep & Pack shown as route-dependent stages
     4. **Returns** (tag: `if returned`)
     5. **Recovery** (tag: `always`)
     Followed by the **Final Commerce Outcome** block.
2. `/app/dashboard` — **Dashboard**: Overview of workflow operations, "About" explanation, and 5 small equal-width agent boxes linking to `/app/agents/:stage`.
3. `/app/review` — **Review Queue**: Lists review candidates, prefills the operator name, records overrides, and resumes workflows.
4. `/app/agents/:stage` — **Agent Detail Page**: Dedicated workspace for each stage with unit order form, preview-only visual uploads, stage-isolated check executions, skipped reasons, cross-tenant refusal, and cryptographic evidence record lookup.
5. `/signin` &rarr; Redirects directly to `/`.
6. `/app/run`, `/app/agents`, `/app/evidence` &rarr; Redirect to `/app/dashboard`.

---

## Installation & Running

### 1. Start the Orchestrator
From the repository root:
```bash
python -m uvicorn orchestration.api:app --port 8100
```

### 2. Install & Start the UI
In a separate terminal:
```bash
cd ui
npm install
npm run dev
```
The application will be running locally at `http://localhost:5173/`.

### 3. Build for Production
```bash
cd ui
npm run build
```
Production assets are emitted to `ui/dist/`.

---

## Verification Screenshots

Screenshots of key application states and workflows are located in `ui/docs/`:
- `01_home_page.png` — Public landing page showing hero, single-row agent cards, and 5-stage sequential workflow cards + Final Commerce Outcome
- `02_dashboard_page.png` — Dashboard with "About" explanation, top bar with org toggle + operator input, and 5 agent boxes
- `03_agent_page_prep.png` — Prep Manager page showing completed check results, checks table, and evidence record
- `04_review_page.png` — Review queue with candidate cards, override panel with prefilled operator, and resume action
