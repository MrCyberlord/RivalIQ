import { createHttpServer } from './http.js';
import { RunManager } from './runs.js';
import { readConfig } from './config.js';

const { port, timeoutMs, baseUrl, allowedOrigin } = readConfig(process.env);
const manager = new RunManager({ baseUrl, timeoutMs, log: entry => console.info(JSON.stringify(entry)) });
const server = createHttpServer(manager, allowedOrigin);
server.requestTimeout = 15000; server.headersTimeout = 10000;
server.listen(port, '127.0.0.1', () => console.info(JSON.stringify({ event: 'orchestration_ready', port })));
