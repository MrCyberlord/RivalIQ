import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { createHttpServer } from '../src/http.js';
import { RunManager } from '../src/runs.js';
import { reportFixture, seller } from './fixture.js';

test('HTTP validation, CORS, live step status, limits and polling never rerun upstream', async t => {
  let calls = 0; let release!: () => void;
  const gate = new Promise<void>(r => { release = r; });
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000,
    fetcher: (async () => { calls++; await gate; return Response.json(reportFixture()); }) as typeof fetch });
  const server = createHttpServer(manager, 'http://localhost:5173');
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { release(); server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const post = (body: unknown, origin = 'http://localhost:5173') => fetch(`${base}/orchestration/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(body) });
  assert.equal((await post(seller, 'https://evil.example')).status, 403);
  assert.equal((await post({ ...seller, selling_price: false })).status, 422);
  assert.equal((await post({ ...seller, product_name: 'a'.repeat(17000) })).status, 413);
  assert.equal(calls, 0);
  const preflight = await fetch(`${base}/orchestration/runs`, { method: 'OPTIONS', headers: { Origin: 'http://localhost:5173' } });
  assert.equal(preflight.status, 204); assert.equal(preflight.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173');
  const response = await post(seller); assert.equal(response.status, 202);
  const { run_id } = await response.json();
  let status = await (await fetch(`${base}/orchestration/runs/${run_id}`)).json();
  assert.equal(status.status, 'running'); assert.ok(status.steps.some((s: {status: string}) => s.status === 'running'));
  assert.equal(status.result, undefined);
  assert.equal((await fetch(`${base}/orchestration/runs/bad`)).status, 400);
  assert.equal((await fetch(`${base}/orchestration/runs/00000000-0000-4000-8000-000000000000`)).status, 404);
  release();
  for (let i = 0; i < 100 && status.status === 'running'; i++) {
    await new Promise(r => setTimeout(r, 5)); status = await (await fetch(`${base}/orchestration/runs/${run_id}`)).json();
  }
  assert.equal(status.status, 'success'); assert.equal(calls, 1);
});
test('bounded concurrent runs reject excess work and expire completed results', async () => {
  let release!: () => void; const gate = new Promise<void>(r => { release = r; });
  const manager = new RunManager({ baseUrl: 'http://backend.test', timeoutMs: 1000, ttlMs: 5,
    fetcher: (async () => { await gate; return Response.json(reportFixture()); }) as typeof fetch });
  const a = await manager.start(seller); const b = await manager.start(seller);
  await assert.rejects(manager.start(seller), /busy/); release();
  await new Promise(r => setTimeout(r, 100)); assert.equal(manager.get(a.run_id), undefined); assert.equal(manager.get(b.run_id), undefined);
});
