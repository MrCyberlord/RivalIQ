import { createStep, createWorkflow } from '@mastra/core/workflows';
import { z } from 'zod';
import { sellerSchema, reportSchema, inspectionSchema, briefSchema, type Report, type StepStatus } from './contracts.js';

export class WorkflowError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
const safeUrl = (value: string | null) => {
  try { const u = new URL(value ?? ''); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password; } catch { return false; }
};
export function inspectReport(report: Report) {
  const ids = new Set(report.listings.map(l => l.id));
  if (ids.size !== report.listings.length) throw new WorkflowError('invalid_report', 'The backend returned duplicate source identifiers.');
  const findings = [report.report.market_overview, ...report.report.competitive_advantages, ...report.report.competitive_threats, ...report.report.pricing_observations, ...report.report.recommendations];
  if (findings.some(f => f.source_ids.some(id => !ids.has(id))) || report.report.classifications.some(c => !ids.has(c.source_id)))
    throw new WorkflowError('invalid_report', 'The backend returned unresolved source references.');
  const p = report.pricing;
  const comparisons = new Set(p.comparisons.map(c => c.source_id));
  const validComparisons = p.comparisons.every(c => report.listings.some(l => l.id === c.source_id && l.comparability.eligible && !l.duplicate_of && l.currency === p.currency && l.listed_price !== null));
  if (p.benchmark_status === 'sufficient' && (p.comparable_price_count < p.minimum_required || comparisons.size !== p.comparable_price_count || !validComparisons || [p.minimum, p.median, p.maximum].some(v => v === null)))
    throw new WorkflowError('invalid_report', 'The backend benchmark lacks sufficient comparable evidence.');
  if (p.benchmark_status === 'insufficient' && [p.minimum, p.median, p.maximum].some(v => v !== null))
    throw new WorkflowError('invalid_report', 'An insufficient benchmark unexpectedly contains primary prices.');
  if (report.persistence.status === 'saved' && !report.persistence.report_id)
    throw new WorkflowError('invalid_report', 'The backend save status is missing its report identifier.');
  const warnings = [];
  if (findings.some(f => f.source_ids.some(id => !safeUrl(report.listings.find(l => l.id === id)?.product_url ?? null)))) warnings.push('Some cited listings have no usable source URL; verify them before acting.');
  if (report.persistence.status !== 'saved') warnings.push('This report was not saved. Check the report saving status below.');
  return inspectionSchema.parse({ benchmark_available: p.benchmark_status === 'sufficient', benchmark_message: p.benchmark_message,
    comparable_count: p.comparable_price_count, broader_market_note: 'Broader market listings are context only; use the backend like-for-like benchmark for comparisons.', warnings,
    sources: report.listings.filter(l => safeUrl(l.product_url)).map(l => ({ source_id: l.id, url: l.product_url!, merchant: l.merchant })),
  });
}
export function buildBrief(report: Report, inspection: z.infer<typeof inspectionSchema>) {
  const p = report.pricing;
  const confidence = p.comparable_price_count === 0 ? 'No comparable offers: reliable like-for-like pricing guidance is unavailable.'
    : p.comparable_price_count === 1 ? 'One comparable offer is an individual observation, not a market benchmark.'
    : p.comparable_price_count < 5 ? 'Two to four comparable offers support directional comparisons only; this is a small sample.'
    : 'Five or more comparable offers support descriptive comparisons, not statistical representativeness.';
  return briefSchema.parse({ ...inspection, recommendations: report.report.recommendations,
    seller_current_price: { amount: p.selling_price, currency: p.currency },
    comparable_evidence: { sample_size: p.comparable_price_count, source_ids: p.comparisons.map(c => c.source_id), minimum: p.minimum, median: p.median, maximum: p.maximum },
    evidence_confidence: confidence,
    suggested_next_steps: [p.comparable_price_count < 2 ? 'Collect more attribute-matched, same-currency offers before relying on a primary benchmark.' : 'Confirm product equivalence and current source prices before acting on this sample.', 'Check your costs, shipping, taxes and fees before testing a promotion.'],
    recommendation_safety_message: report.recommendation_safety?.message ?? 'This older report has no recorded recommendation safety status; review its advice carefully.',
    save_status: report.persistence.status, report_id: report.persistence.report_id,
    limitations: ['Recommendations come from the FastAPI report, including labeled deterministic replacements where necessary; AI conclusions remain unverified.', 'Broader market observations are excluded from comparable pricing evidence.', 'No additional discovery, model inference or price prediction was performed by this workflow.', ...report.caveats],
  });
}
export function makeWorkflow(options: { baseUrl: string; timeoutMs: number; fetcher?: typeof fetch; onStep?: (step: StepStatus) => void; onError?: (error: WorkflowError) => void }) {
  let called = false;
  async function tracked<T>(id: string, action: () => Promise<T> | T): Promise<T> {
    const start = performance.now(); options.onStep?.({ id, status: 'running', duration_ms: null });
    try { const value = await action(); options.onStep?.({ id, status: 'success', duration_ms: Math.round(performance.now() - start) }); return value; }
    catch (error) { options.onError?.(error instanceof WorkflowError ? error : new WorkflowError('workflow_failed', 'A workflow validation step failed. Check history before retrying.')); options.onStep?.({ id, status: 'failed', duration_ms: Math.round(performance.now() - start) }); throw error; }
  }
  const accept = createStep({ id: 'accept-seller', inputSchema: sellerSchema, outputSchema: sellerSchema,
    execute: async ({ inputData }) => tracked('accept-seller', () => sellerSchema.parse(inputData)) });
  const call = createStep({ id: 'fastapi-intelligence', inputSchema: sellerSchema, outputSchema: reportSchema,
    execute: async ({ inputData }) => tracked('fastapi-intelligence', async () => {
      if (called) throw new WorkflowError('duplicate_call_blocked', 'This run already invoked analysis.');
      called = true;
      try {
        const response = await (options.fetcher ?? fetch)(new URL('/api/intelligence', options.baseUrl), {
          method: 'POST', redirect: 'error', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(inputData), signal: AbortSignal.timeout(options.timeoutMs),
        });
        if (!response.ok) throw new WorkflowError('upstream_failure', `FastAPI analysis failed (HTTP ${response.status}). No automatic retry was attempted.`);
        const reader = response.body?.getReader();
        if (!reader) throw new WorkflowError('invalid_report', 'The backend returned no report.');
        const chunks: Uint8Array[] = []; let size = 0;
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          size += value.byteLength;
          if (size > 2_000_000) { await reader.cancel(); throw new WorkflowError('invalid_report', 'The backend report exceeded the response limit.'); }
          chunks.push(value);
        }
        const text = Buffer.concat(chunks).toString('utf8');
        const parsed = reportSchema.safeParse(JSON.parse(text));
        if (!parsed.success) throw new WorkflowError('invalid_report', 'The backend returned an incompatible report.');
        return parsed.data;
      } catch (error) {
        if (error instanceof WorkflowError) throw error;
        if (error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)) throw new WorkflowError('timeout', 'Analysis timed out. It may still finish and save in FastAPI; check history before running again.');
        throw new WorkflowError('upstream_unavailable', 'FastAPI is unavailable or returned an invalid response. Check history before retrying.');
      }
    }) });
  const inspected = z.object({ report: reportSchema, inspection: inspectionSchema });
  const inspect = createStep({ id: 'inspect-evidence', inputSchema: reportSchema, outputSchema: inspected,
    execute: async ({ inputData }) => tracked('inspect-evidence', () => inspected.parse({ report: inputData, inspection: inspectReport(inputData) })) });
  const output = z.object({ report: reportSchema, action_brief: briefSchema });
  const brief = createStep({ id: 'seller-action-brief', inputSchema: inspected, outputSchema: output,
    execute: async ({ inputData }) => tracked('seller-action-brief', () => output.parse({ report: inputData.report, action_brief: buildBrief(inputData.report, inputData.inspection) })) });
  return createWorkflow({ id: 'rivaliq-guided-analysis', inputSchema: sellerSchema, outputSchema: output, retryConfig: { attempts: 0, delay: 0 }, options: { validateInputs: true, autoRestartActiveRuns: false, shouldPersistSnapshot: () => false } })
    .then(accept).then(call).then(inspect).then(brief).commit();
}
