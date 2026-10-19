import type { Intelligence, ProductAttributes, Finding } from './api';
export interface GuidedRun {
  run_id: string; status: 'running' | 'success' | 'failed'; duration_ms: number | null;
  steps: { id: string; status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'; duration_ms: number | null }[];
  error?: { code: string; message: string };
  result?: { report: Intelligence; action_brief: {
    benchmark_available: boolean; benchmark_message: string; comparable_count: number;
    seller_current_price: { amount: string; currency: string };
    comparable_evidence: { sample_size: number; source_ids: string[]; minimum: string | null; median: string | null; maximum: string | null };
    evidence_confidence: string; suggested_next_steps: string[]; recommendation_safety_message: string;
    broader_market_note: string; warnings: string[]; recommendations: Finding[];
    sources: { source_id: string; url: string; merchant: string | null }[];
    save_status: 'saved' | 'disabled' | 'error'; report_id: string | null; limitations: string[];
  } };
}
async function request(url: string, init?: RequestInit) {
  let response: Response;
  try { response = await fetch(url, { ...init, signal: AbortSignal.timeout(20000) }); }
  catch { throw new Error('Guided analysis service is unavailable. Direct analysis remains available. Check history before starting another run.'); }
  const data = await response.json().catch(() => null);
  if (!response.ok || !data) throw new Error(data?.error?.message ?? 'Guided analysis service is unavailable. Check report history before retrying.');
  return data;
}
export async function runGuidedAnalysis(product: string, price: string, cost: string, attributes: Partial<ProductAttributes>, onStatus: (run: GuidedRun) => void): Promise<GuidedRun> {
  const started = await request('/orchestration/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_name: product, selling_price: price, cost: cost || null, seller_attributes: attributes }) });
  const deadline = Date.now() + 620000;
  while (Date.now() < deadline) {
    const run: GuidedRun = await request(`/orchestration/runs/${encodeURIComponent(started.run_id)}`);
    onStatus(run);
    if (run.status === 'failed') throw new Error(run.error?.message ?? 'Guided analysis failed. Check history before retrying.');
    if (run.status === 'success') return run;
    await new Promise(resolve => window.setTimeout(resolve, 1000));
  }
  throw new Error('Stopped waiting for the workflow. It may still finish. Check report history before running again.');
}
