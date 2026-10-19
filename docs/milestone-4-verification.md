# Milestone 4 verification

Verified 2026-10-19. Backend `.env` was preserved. Only credential-presence booleans were inspected; no API key was printed.

Final checks: **225 backend tests passed**, explicit TypeScript checking passed, the Vite production build passed, and `pip check` reported no broken requirements. The existing upstream Starlette TestClient deprecation warning remains.

- Confirmed official hosted `tabpfn-client` authentication/regression documentation and installed version 0.6.1. Inspected the installed public token setter, regressor constructor, fit/predict signatures and SDK HTTP error wrapping.
- Installed the optional requirements and checked dependency consistency. The SDK resolved Pydantic to 2.13.4; prior functionality is covered by the full regression suite under that environment.
- Unit tests mock database and hosted model/auth behavior. They cover snapshot retention, search-scoped deduplication, independent-product grouping, comparability/currency/time filtering, minimum thresholds, feature leakage, response invariants, optional SDK errors, quota/auth failures and killable worker timeout behavior. No test uploads data or consumes hosted credits.
- The real Atlas eligibility check succeeded for the default Milton / bottle / 1000 ml / stainless steel / India / INR cohort, returning `insufficient_data`: **0 eligible independent products**, against the required 30 products / 3 brands / 5 requested-brand products.
- `TABPFN_API_KEY` was present, but no hosted fit or predict was attempted because sufficient genuine history was unavailable. No data was fabricated/backfilled and no discovery calls were made to force a pass. This milestone's live check used **zero Prior Labs inference calls and zero SerpApi searches**.

Not live-verified: token validity, model entitlements, hosted quota behavior, end-to-end inference latency, actual model outputs or accuracy/calibration on held-out real observations. These require genuinely sufficient history and an explicit consented hosted call. The minimum is a conservative application policy, not a statistical accuracy guarantee.

Reproduce eligibility only:

```powershell
.\.venv\Scripts\python.exe backend/scripts/check_pricing.py
```

After adequate real observations exist, opt into a hosted smoke test with `--allow-cloud-processing`. Merely generating or reopening reports never requests TabPFN inference.
