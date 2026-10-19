import { createServer } from 'node:http';
import { z } from 'zod';
import { RunManager } from './runs.js';
import { WorkflowError } from './workflow.js';

export function createHttpServer(manager: RunManager, allowedOrigin: string) {
  return createServer(async (req, res) => {
    res.setHeader('Cache-Control', 'no-store'); res.setHeader('Content-Type', 'application/json');
    const send = (status: number, data: unknown) => { res.writeHead(status); res.end(JSON.stringify(data)); };
    const origin = req.headers.origin;
    if (origin && origin !== allowedOrigin) { send(403, { error: { code: 'origin_denied', message: 'Origin is not allowed.' } }); return; }
    if (origin) { res.setHeader('Access-Control-Allow-Origin', origin); res.setHeader('Vary', 'Origin'); }
    if (req.method === 'OPTIONS') {
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'); res.setHeader('Access-Control-Allow-Headers', 'Content-Type'); send(204, undefined); return;
    }
    const path = req.url?.split('?')[0];
    try {
      if (req.method === 'GET' && path === '/orchestration/health') { send(200, { status: 'ok', workflow: 'rivaliq-guided-analysis' }); return; }
      if (req.method === 'POST' && path === '/orchestration/runs') {
        if (!req.headers['content-type']?.startsWith('application/json')) { send(415, { error: { code: 'content_type', message: 'Use application/json.' } }); return; }
        const chunks: Buffer[] = []; let size = 0;
        for await (const chunk of req) { size += chunk.length; if (size > 16384) { send(413, { error: { code: 'too_large', message: 'Request is too large.' } }); return; } chunks.push(chunk); }
        const record = await manager.start(JSON.parse(Buffer.concat(chunks).toString('utf8')));
        send(202, { run_id: record.run_id, status: record.status }); return;
      }
      if (req.method === 'GET' && path?.startsWith('/orchestration/runs/')) {
        const id = path.slice('/orchestration/runs/'.length);
        if (!z.uuid().safeParse(id).success) { send(400, { error: { code: 'invalid_id', message: 'Invalid workflow run identifier.' } }); return; }
        const run = manager.get(id);
        if (!run) { send(404, { error: { code: 'not_found', message: 'Run not found or expired. Check report history; do not automatically rerun.' } }); return; }
        send(200, run); return;
      }
      send(404, { error: { code: 'not_found', message: 'Endpoint not found.' } });
    } catch (error) {
      if (error instanceof z.ZodError || error instanceof SyntaxError) send(422, { error: { code: 'invalid_request', message: 'Invalid seller product details or JSON.' } });
      else if (error instanceof WorkflowError && error.code === 'busy') send(503, { error: { code: error.code, message: error.message } });
      else send(500, { error: { code: 'internal_error', message: 'Workflow service failed. Check history before retrying.' } });
    }
  });
}
