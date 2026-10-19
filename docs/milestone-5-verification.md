# Milestone 5 verification

Verified locally on 2026-10-19 with Node 24.19.0, npm 11.17.0 and Python 3.14.7.
Official `@mastra/core` 1.78.0 requires Node >=22.13.0. The current official
workflow documentation and installed declarations were checked before implementation.

## Automated checks

- Backend: **225 passed**, one existing upstream Starlette TestClient deprecation warning.
- Orchestration TypeScript check and build: passed.
- Frontend TypeScript check and Vite production build: passed.
- **18 passed** orchestration, HTTP, configuration, client and React rendering tests.
  Actual Mastra engine tests use mocked upstream services (no external calls).
- npm audit reported **five moderate** dependency findings through Mastra's
  `gray-matter → js-yaml → argparse → sprintf-js` dependency chain. npm suggests
  downgrading Mastra to 1.0.4, which is not applied. No high/critical findings.
  The application does not parse Markdown/front matter; recheck upstream patches
  before exposing the service beyond its local single-user scope.
- Windows sandbox initially blocked tsx's OS user-info lookup; mocked Node tests
  passed outside that sandbox. The production service uses compiled JavaScript.

## Real local workflow (not mocked)

Exactly one workflow was submitted through the actual Node HTTP server and Mastra
engine to the already-running FastAPI server. No automated retries were made.

- Workflow run ID: `f1610f48-0c2d-4f6b-99b3-4de8e77ba17e`.
- FastAPI request ID: `eef2fa8eb38d48e6b84af2432d640ac3`.
- Saved Atlas report ID: `6ad5acd2fa74d8cc6a31ab75`.
- Six source listings; backend benchmark status: `sufficient`.
- All four Mastra steps succeeded; upstream call counter: **1**.
- FastAPI timing metadata recorded **2 SerpApi** and **2 Ollama** stages, all OK.
- Atlas save succeeded; GET report returned matching narrative content.
- **0 TabPFN calls**, no additional LLM or source website fetches by orchestration.
- Existing FastAPI remains responsible for discovery observation persistence; the
  smoke check did not independently count observation documents or Sentry events.

| Measurement | Time |
| --- | ---: |
| Mastra workflow total | 83.527 s |
| FastAPI HTTP step | 83.510 s |
| Evidence inspection | 0.003 s |
| Brief mapping | 0.002 s |
| FastAPI analysis (before report save) | 83.081 s |
| Atlas report save | 0.384 s |
| Gemma discovery | 13.264 s |
| SerpApi search 1 | 5.817 s |
| SerpApi search 2 | 4.149 s |
| Gemma report | 59.798 s |
| Smoke client wall time (includes poll and reopen) | 84.388 s |

Ollama discovery metadata: load 8.953 s, prompt evaluation 2.462 s, generation
1.458 s. Report metadata: load 0.062 s, prompt evaluation 24.000 s, generation
35.368 s (928 prompt tokens, 293 output tokens, 8.28 output tokens/s).
Remaining latency is primarily local Gemma inference; orchestration adds about
17 ms outside its FastAPI step in this one sample. This is a single real run,
not a performance guarantee or a warm/cold benchmark study.

The live report remains in the user's existing Atlas history. Node run memory
is temporary. No deployment, public authentication or multi-process run recovery
was tested. Browser layout is responsive in code; automated compatibility tests
are HTTP/client/SSR checks, not a browser end-to-end or visual test.
