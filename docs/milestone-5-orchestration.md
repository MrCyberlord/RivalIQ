# Optional local Mastra orchestration

FastAPI remains the source of truth. The Node service has no SerpApi, Ollama,
MongoDB, Sentry or TabPFN credentials and uses no additional LLM. There is no
Mastra account, hosted platform, CLI, Studio or Mastra API key requirement.

```text
React :5173 ─ /api/* ────────────────────────> FastAPI :8000
      └───── /orchestration/* ─> Node :4111 ─> POST /api/intelligence (once)
                                            discovery → matching → pricing
                                            → Gemma → MongoDB
Node: validate seller → invoke FastAPI → inspect evidence → deterministic brief
React: explicit consent + prediction action ─> FastAPI /api/pricing/predict
```

`@mastra/core` is pinned to 1.78.0 (npm latest checked during implementation).
Its declared Node engine is `>=22.13.0`; tested with Node 24.19.0.
The implementation uses the official [workflow APIs](https://mastra.ai/docs/workflows/overview):
`createStep`, `createWorkflow`, `.then()`, `.commit()`, `createRun` and `run.start`.
Zod validates every boundary. Outputs are explicitly parsed because input
validation alone does not guarantee validated step outputs.

## Windows PowerShell startup

Run these from the repository root. Keep existing `backend/.env` unchanged.
Install dependencies once:

```powershell
node --version
npm.cmd ci
if (-not (Test-Path orchestration/.env)) { Copy-Item orchestration/.env.example orchestration/.env }
```

In three separate terminals:

```powershell
# Terminal 1 (existing Python virtual environment and backend configuration)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
# Terminal 2
npm.cmd run dev:orchestration
# Terminal 3
npm.cmd run dev
```

Equivalent startup scripts: `scripts/start-backend.ps1`, `start-orchestration.ps1`
and `start-frontend.ps1`. Invoke with `powershell -File .\scripts\start-orchestration.ps1`
if permitted by your PowerShell execution policy. No policy change is required
when using the npm/Python commands above. Orchestration `dev` compiles then starts;
restart it after changes (no background watcher).

Open **http://localhost:5173**. Original **Generate intelligence report** uses
FastAPI directly. **Run guided analysis** opts into Mastra. The UI polls step
status once per second. Service failure never triggers another analysis or
silently switches to the direct button. Check history before manually retrying.

Only the optional Node service reads `orchestration/.env`:

| Setting | Default | Meaning |
| --- | --- | --- |
| FASTAPI_BASE_URL | http://127.0.0.1:8000 | Server-side backend origin, no path/credentials/query |
| ORCHESTRATION_PORT | 4111 | Loopback listener, 1024–65535 |
| ORCHESTRATION_TIMEOUT_MS | 420000 | One upstream call, bounded 1000–600000 ms |
| CORS_ORIGIN | http://localhost:5173 | Exact allowed browser origin; use http://127.0.0.1:5173 if browsing there |

Vite's two development proxy targets are configured in `frontend/vite.config.ts`.
If changing either service port, update its proxy too. The backend origin must
point directly to FastAPI, never Vite or this orchestration service. Credentials
stay exclusively in backend configuration; no new `VITE_*` secret variables.
Ollama's existing port is 11434; Atlas uses its existing outbound connection.

## API and guarantees

- `GET /orchestration/health`: local service liveness, not an upstream probe.
- `POST /orchestration/runs`: strict seller input matching the current UI and
  backend defaults; returns **202** `{run_id,status}`. No automatic retries.
- `GET /orchestration/runs/{uuid}`: `running`, `success` or `failed`, safe step
  statuses/durations, upstream call count and completion duration. Success adds
  `{result:{report,action_brief}}`; failure adds `{error:{code,message}}`.
  This GET never calls FastAPI or starts/restarts a workflow.
- HTTP boundary errors use `{error:{code,message}}`: 400 invalid ID, 403 origin,
  404 unknown/expired run, 413 body over 16 KiB, 415 content type, 422 invalid
  JSON/input, 503 capacity. Workflow failures are returned in the polled run.
  Upstream non-2xx/invalid reports/timeouts have safe stable error codes; raw
  upstream errors or bodies are never forwarded as errors.

The four real Mastra steps validate seller details, make exactly one FastAPI
intelligence request, inspect references/comparability/save status, then map
the returned report into a brief. The workflow checks primary benchmark
sufficiency, duplicate/eligible/same-currency comparison references, known
citations and saved IDs. Missing or unsafe HTTP source URLs are disclosed and
excluded from brief links. It never fetches those URLs. A mismatched report fails
honestly; it does not repair data, infer specifications or invent citations.

The brief maps the three evidence-linked, safety-checked FastAPI recommendations
(including explicitly disclosed deterministic replacements in Milestone 5.1),
exposes the backend benchmark decision and save status, separates broader market
context, and states limitations. It is deterministic and adds no new model
claims. It includes the seller's current price, comparable source IDs and
aggregates, sample confidence, limitations and suggested verification steps.
Neither the workflow nor these checks verifies AI conclusions or prices.
TabPFN remains a separate user action requiring explicit cloud-processing consent.

Retries and automatic workflow recovery/snapshot persistence are disabled. A
single-use call guard prevents a repeated step from spending search credits.
One *successful* intelligence call internally uses up to two SerpApi searches,
two Gemma calls, discovery-observation writes and one report write, all owned
by FastAPI. Polls, evidence inspection and brief generation add none.

## Privacy, observability and operational limits

The Node process receives seller details and the returned report in local
memory. It has no database and makes no hosted Mastra/LLM calls. SDK logging is
disabled; explicit JSON completion logs contain only random run IDs, fixed step
names, statuses, durations, call counts and allowlisted error codes. FastAPI's
existing Sentry privacy protections and local stage timings remain untouched.
Full inputs, report text, URLs and credentials are not logged by this service.

Runs are process-local and results expire after ten minutes (pruned on the next
API access). Restart loses run state, not MongoDB-saved reports. At most two runs
can execute simultaneously and fifty records can remain in memory. Requests
are bounded to 16 KiB and report responses to 2 MB. Incoming bodies have a
15-second timeout; upstream analysis has its separate configured timeout.
A timeout/client disconnect cannot guarantee cancellation of FastAPI's external
work; check history before retrying. No global idempotency across separate POSTs
or process restarts is claimed. Separate user clicks are separate paid analyses.

This is an optional **local**, single-user service bound to 127.0.0.1. Before any
deployment, add authentication/authorization, per-user rate limits and protected
reverse proxies for `/api` and `/orchestration`. CORS is not authentication. A
multi-process deployment needs shared run state and cross-request idempotency;
neither is introduced here. Configure proxy timeouts intentionally and avoid
raw request logging/tracing. Static Vite builds require reverse proxy routing;
the development proxy is not deployed. No Render deployment has been added.

## Verification and explicit live check

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd run check --workspace orchestration
npm.cmd run test:orchestration
npm.cmd run build:all
```

Frontend `build` includes `tsc --noEmit`. Tests execute the actual Mastra engine
against mocked FastAPI responses: steps, strict validation, exact report
passthrough, brief mapping, citations, misleading benchmarks, one-call behavior,
API failures, timeouts, HTTP CORS/limits/status polling, capacity/expiry and
frontend direct/guided separation. Tests make no SerpApi, Gemma, Atlas or TabPFN
calls. They do not prove browser visual behavior or external service availability.

With all three services running and the existing backend credentials configured,
this **explicit paid live check** submits one real workflow (up to two SerpApi
searches, two Gemma calls, a report write and observation writes):

```powershell
.\.venv\Scripts\python.exe orchestration/scripts/smoke.py --allow-paid-searches
```

It prints only run/stage timing metadata, counts, benchmark/save status and
whether the saved report reopens identically. It does not invoke TabPFN.
Use `--product` and `--selling-price` to change the sample; the smoke check's
explicit bottle attributes are for the default bottle and must be changed in
the script for a different product category. See the verification record for
actual results; mocked test timings are not live performance measurements.
