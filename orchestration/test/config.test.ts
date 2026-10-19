import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readConfig } from '../src/config.js';
test('server configuration has safe defaults and rejects cycles, credentials and unbounded timeouts', () => {
  assert.deepEqual(readConfig({}), { port: 4111, timeoutMs: 420000, baseUrl: 'http://127.0.0.1:8000', allowedOrigin: 'http://localhost:5173' });
  for (const env of [ { FASTAPI_BASE_URL: 'http://localhost:4111' }, { FASTAPI_BASE_URL: 'http://user:secret@localhost:8000' },
    { FASTAPI_BASE_URL: 'http://localhost:8000/api' }, { FASTAPI_BASE_URL: 'secret-invalid-url' }, { ORCHESTRATION_TIMEOUT_MS: '0' },
    { ORCHESTRATION_TIMEOUT_MS: '700000' }, { CORS_ORIGIN: '*' }, { CORS_ORIGIN: 'http://localhost:5173/private' } ]) {
    assert.throws(() => readConfig(env), error => error instanceof Error && !error.message.includes('secret'));
  }
});
