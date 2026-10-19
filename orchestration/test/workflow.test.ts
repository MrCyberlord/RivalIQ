import { test } from 'node:test';
import assert from 'node:assert/strict';
import { RunManager } from '../src/runs.js';
import { reportSchema, sellerSchema, stepIds } from '../src/contracts.js';
import { inspectReport, buildBrief } from '../src/workflow.js';
import { reportFixture, seller } from './fixture.js';

const mockFetch = (callback: (...args: Parameters<typeof fetch>) => Promise<Response>) => callback as typeof fetch;
async function finished(manager: RunManager, id: string) {
  const deadline = Date.now() + 10000;
  while (manager.get(id)?.status === 'running') { if (Date.now() > deadline) throw new Error('test deadline'); await new Promise(r => setTimeout(r, 5)); }
  return manager.get(id)!;
}
test('actual Mastra steps succeed, preserve report and call only FastAPI intelligence once', async () => {
  const calls: string[] = []; const logs: object[] = [];
  const fixture = reportFixture();
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000, log: e => logs.push(e),
    fetcher: mockFetch(async (url, init) => { calls.push(String(url)); assert.equal(init?.method, 'POST'); assert.equal(JSON.parse(String(init.body)).product_name, seller.product_name); return Response.json(fixture); }) });
  const run = await manager.start(seller); const result = await finished(manager, run.run_id);
  assert.equal(result.status, 'success'); assert.match(result.run_id, /^[a-f0-9-]{36}$/);
  assert.deepEqual(result.steps.map(s => [s.id, s.status]), stepIds.map(id => [id, 'success']));
  assert.deepEqual(result.result?.report, fixture);
  assert.deepEqual(calls, ['http://backend.test/api/intelligence']);
  for (let n = 0; n < 5; n++) manager.get(run.run_id);
  assert.equal(calls.length, 1); assert.ok(!JSON.stringify(logs).includes(seller.product_name));
  assert.ok(!JSON.stringify(logs).includes('shop.example'));
});
test('seller validation rejects malformed and unknown input before any call', async () => {
  let count = 0;
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000, fetcher: mockFetch(async () => { count++; return Response.json({}); }) });
  for (const input of [{ ...seller, selling_price: true }, { ...seller, selling_price: '0' }, { ...seller, selling_price: '2.345' }, { ...seller, product_name: ' ' }, { ...seller, allow_cloud_processing: true }, { ...seller, max_results: 7 }]) await assert.rejects(manager.start(input));
  assert.equal(count, 0); assert.equal(sellerSchema.parse(seller).market, 'India');
});
test('brief retains recommendations, sources and insufficient benchmark without invented prices', () => {
  const report = reportSchema.parse(reportFixture());
  const brief = buildBrief(report, inspectReport(report));
  assert.equal(brief.benchmark_available, false); assert.equal(brief.save_status, 'disabled');
  assert.deepEqual(brief.recommendations, report.report.recommendations);
  assert.equal(brief.sources[0].url, report.listings[0].product_url);
  assert.equal('predicted_price' in brief, false);
  assert.deepEqual(brief.seller_current_price, { amount: '150', currency: 'INR' });
  assert.equal(brief.comparable_evidence.median, null);
  assert.match(brief.evidence_confidence, /individual observation/);
});

for (const count of [0, 1, 2, 5]) test(`brief maps ${count} comparable offers without broader-market contamination`, () => {
  const report = reportSchema.parse(reportFixture());
  const base = report.listings[0];
  report.listings = Array.from({ length: count }, (_, i) => ({ ...base, id: `L${i + 1}`, listed_price: 100 + i, product_url: `https://shop.example/${i}` }));
  report.listings.push({ ...base, id: 'L99', listed_price: 1, comparability: { category: 'uncertain', eligible: false, reason: 'Unknown attributes' } });
  if (!count) {
    for (const f of [report.report.market_overview, ...report.report.competitive_threats, ...report.report.pricing_observations, ...report.report.recommendations]) f.source_ids = ['L99'];
    report.report.classifications = [{ source_id: 'L99', category: 'uncertain', reason: 'Unknown' }];
  }
  report.pricing.comparable_price_count = count;
  report.pricing.comparisons = Array.from({ length: count }, (_, i) => ({ source_id: `L${i + 1}`, listed_price: String(100 + i), seller_minus_listing: String(50 - i), seller_difference_percent: null }));
  report.pricing.benchmark_status = count >= 2 ? 'sufficient' : 'insufficient';
  report.pricing.minimum = count >= 2 ? '100' : null;
  report.pricing.median = count >= 2 ? '101' : null;
  report.pricing.maximum = count >= 2 ? String(99 + count) : null;
  const brief = buildBrief(report, inspectReport(report));
  assert.equal(brief.comparable_evidence.sample_size, count);
  assert.equal(brief.comparable_evidence.source_ids.length, count);
  assert.ok(!brief.comparable_evidence.source_ids.includes('L99'));
  assert.deepEqual(brief.recommendations, report.report.recommendations);
  assert.ok(brief.suggested_next_steps.every(s => s.length > 0));
  assert.match(brief.evidence_confidence, count === 0 ? /unavailable/ : count === 1 ? /individual observation/ : count === 2 ? /small sample/ : /not statistical representativeness/);
});
test('unresolved references and misleading benchmarks fail inspection', () => {
  const r = reportSchema.parse(reportFixture()); r.report.recommendations[0].source_ids = ['L99']; assert.throws(() => inspectReport(r));
  const p = reportSchema.parse(reportFixture()); p.pricing.median = '100'; assert.throws(() => inspectReport(p));
  p.pricing.benchmark_status = 'sufficient'; assert.throws(() => inspectReport(p));
});
test('unsafe or missing links remain unavailable and never become invented citations', () => {
  const r = reportSchema.parse(reportFixture()); r.listings[0].product_url = 'javascript:alert(1)';
  const inspection = inspectReport(r); assert.equal(inspection.sources.length, 0); assert.equal(inspection.warnings.length, 2);
});
for (const status of [401, 429, 500, 503]) test(`upstream HTTP ${status} fails once and skips later steps`, async () => {
  let calls = 0;
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000,
    fetcher: mockFetch(async () => { calls++; return new Response('secret upstream payload', { status }); }) });
  const run = await manager.start(seller); const result = await finished(manager, run.run_id);
  assert.equal(calls, 1); assert.equal(result.status, 'failed'); assert.equal(result.error?.code, 'upstream_failure');
  assert.deepEqual(result.steps.map(s => s.status), ['success', 'failed', 'skipped', 'skipped']);
  assert.ok(!JSON.stringify(result).includes('secret upstream payload'));
});
test('timeout is bounded and does not retry', async () => {
  let calls = 0;
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 20,
    fetcher: mockFetch(async (_url, init) => { calls++; return new Promise((_, reject) => init?.signal?.addEventListener('abort', () => reject(init.signal!.reason))); }) });
  const run = await manager.start(seller); const result = await finished(manager, run.run_id);
  assert.equal(calls, 1); assert.equal(result.error?.code, 'timeout'); assert.match(result.error!.message, /history/);
});
test('network and invalid response errors are safe', async () => {
  for (const fetcher of [mockFetch(async () => { throw new Error('credential=secret'); }), mockFetch(async () => Response.json({ bad: true })), mockFetch(async () => new Response('not json'))]) {
    const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000, fetcher });
    const run = await manager.start(seller); const result = await finished(manager, run.run_id);
    assert.equal(result.status, 'failed'); assert.ok(!JSON.stringify(result).includes('credential='));
  }
});
