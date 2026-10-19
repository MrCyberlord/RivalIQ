import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runGuidedAnalysis } from '../../frontend/src/guided.ts';

test('frontend guided client polls one run and never falls back or invokes prediction', async () => {
  const original = globalThis.fetch; const calls: string[] = [];
  globalThis.fetch = (async (url: string | URL | Request) => {
    calls.push(String(url));
    return Response.json(calls.length === 1 ? { run_id: 'test-run', status: 'running' } : { run_id: 'test-run', status: 'success', steps: [], duration_ms: 1, result: {} });
  }) as typeof fetch;
  try {
    let updates = 0; await runGuidedAnalysis('Test', '100', '', {}, () => updates++);
    assert.equal(updates, 1); assert.deepEqual(calls, ['/orchestration/runs', '/orchestration/runs/test-run']);
  } finally { globalThis.fetch = original; }
});
test('frontend guided failure does not trigger direct or cloud calls', async () => {
  const original = globalThis.fetch; let count = 0;
  globalThis.fetch = (async () => { count++; throw new Error('unavailable'); }) as typeof fetch;
  try { await assert.rejects(runGuidedAnalysis('Test', '100', '', {}, () => {}), /Direct analysis remains available/); assert.equal(count, 1); }
  finally { globalThis.fetch = original; }
});
test('direct frontend endpoint and optional cloud consent path remain separate', async () => {
  const api = await readFile(new URL('../../frontend/src/api.ts', import.meta.url), 'utf8');
  const panel = await readFile(new URL('../../frontend/src/components/IntelligencePanel.tsx', import.meta.url), 'utf8');
  assert.match(api, /fetch\('\/api\/intelligence'/); assert.match(api, /allow_cloud_processing: true/);
  assert.match(panel, /Generate intelligence report/); assert.match(panel, /Run guided analysis/);
  assert.match(panel, /: await analyzeCompetitors/);
});
