# Milestone 5.1: seller-centric intelligence

FastAPI still owns discovery, attribute matching, Decimal price calculations,
Gemma analysis and report persistence. Mastra remains an optional caller of the
same endpoint. Search, history, direct analysis, opt-in TabPFN and existing
Sentry privacy controls remain intact. No dependencies, credentials, services,
model calls or deployments were added.

## Recommendation policy

The Gemma report prompt explicitly treats competitor listings as evidence, never
products the seller controls. It requests seller-directed actions, cites actual
listing IDs, forbids invented numerical targets/specifications and guaranteed
outcomes, and explains that the lowest competitor price is not automatically
optimal. Retrieved content remains untrusted data under the existing system
instructions. Python still performs all price arithmetic.

`backend/app/services/recommendation_safety.py` applies deterministic checks to
each recommendation draft, before final public Pydantic validation and saving:

- Require seller-oriented wording and valid, nonduplicate source citations.
  Inline listing IDs must also be cited. Unknown/missing IDs are replaced,
  never guessed or silently removed from otherwise unsupported advice.
- Reject recognizable instructions to control competitor listings.
- Reject explicit numerical proposed price changes, even if a target equals an
  observed competitor price: observation alone does not establish a justified
  selling target. Contextual current/observed prices and cautious seller-directed
  review or conditional promotion advice remain allowed.
- Reject unsupported numeric figures/percentages and recognizable promises of
  profits, sales, demand, optimal pricing or competitive advantage.
- Prevent broader/unknown matches from supporting a like-for-like price claim.
- Replace invalid or missing actions individually with conservative, cited
  seller guidance. Retain valid actions and return three recommendations.

`recommendation_safety` discloses passed/adjusted status, replacement count,
allowlisted reasons and policy version. Original unsafe model text is not added
to logs or reports. This is deterministic fallback **guidance**, not a fabricated
model response or a silently replaced failed live analysis.

Only recommendation drafts receive this recovery. Malformed JSON, incomplete
model envelopes, invalid non-recommendation findings/citations, provider failures
and unsupported competitive price claims still fail under the existing error
handling. The output report retains strict Pydantic `Finding` constraints and
three recommendations. No retry consumes additional credits.

## Evidence tiers

Only the existing unique, same-currency, attribute-eligible price comparisons
count toward these tiers. Broader market statistics remain separate.

| Comparable offers | Guidance |
| --- | --- |
| 0 | Reliable like-for-like pricing guidance unavailable; gather matched offers |
| 1 | One individual observation, not a market benchmark |
| 2–4 | Directional comparisons only, explicitly limited small sample |
| 5+ | Descriptive comparisons, without statistical representativeness claims |

The primary minimum remains **two**. Zero/one primary min/median/max remain null.
Additive `evidence_quality` and `recommendation_safety` response fields preserve
the existing API structure and saved schema version. Reopening older reports
applies the same policy to a read view without provider calls or rewriting the
historical MongoDB document. Their source evidence and prices are preserved.

## Mastra and React

Mastra deterministically maps the validated FastAPI report into seller current
price/currency, comparable sample and source IDs, primary aggregates (when
available), sample-confidence explanation, recommendations, source links,
save status, limitations and suggested verification steps. No second model,
discovery, MongoDB write or automatic TabPFN prediction is introduced.

React separates **What the data shows**, **What the seller could do**, and
**What remains uncertain** in the guided brief. Recommendations in the original
report and reopened history also show safety disclosures and evidence quality.

Examples (illustrative, not live market findings):

| Unsafe draft | Conservative replacement |
| --- | --- |
| Reduce listing L5's price to INR 380. | Review your own price against comparable offers; with a small sample, use directional comparisons only. |
| Maintain L2 and L3 at INR 391. | Check your own stated specifications against the cited listings before repositioning. |
| Set your price to INR 380 to guarantee profit. | Consider a promotion only after confirming product equivalence, your costs and fees; no outcome is assured. |

Valid advice such as “Review whether your INR 799 price is justified relative
to comparable offers” is retained when there is comparable evidence and the
seller price matches the report. The zero-offer case instead explains that
like-for-like pricing guidance is unavailable.

## Verification and limits

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd run test:orchestration
npm.cmd run check --workspace orchestration
npm.cmd run build:all
```

Verified: **256 backend tests** and **22 Mastra/HTTP/client/React tests** pass;
orchestration and frontend TypeScript checks and production builds pass.
One existing upstream Starlette TestClient deprecation warning remains.
Regression coverage includes competitor-directed advice, numerical targets,
guaranteed outcomes, missing/fabricated citations, valid seller reviews,
0/1/2/5 comparable offers, single-call workflow behavior, brief mapping and
safe legacy report reopening without provider calls. Three former rejection
cases (unsafe/missing recommendation citations and missing action) now test
successful deterministic repair; unrelated structured-output errors still fail.

All automated upstream services were mocked. **No live smoke test or external
provider calls were performed for Milestone 5.1.** Milestone 5's live timing
record is historical and does not validate these new prompts.

A local synthetic microbenchmark of five evidence rows and three empty drafts,
1,000 safety passes, measured approximately **0.022 ms per pass** on this
machine. This measures deterministic fallback handling only, not model latency
or every text-check path. The prompt is slightly longer; its effect on Gemma
latency and recommendation quality has not been measured live. There are no
additional network/model calls and no architectural performance change.

Rules are conservative English-language heuristics, not semantic proof. They
may reject legitimate phrasing or miss subtle/multilingual unsafe advice.
Source citations prove traceability, not accuracy, authenticity, product
equivalence or an optimal price. Five offers are still not a representative
market survey. Model facts outside the recommendation safety checks remain
subject to the existing validation and visible AI limitations. Old invalid
non-recommendation report structures still return the existing retrieval error.
