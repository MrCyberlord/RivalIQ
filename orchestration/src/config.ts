export function readConfig(env: NodeJS.ProcessEnv) {
  try {
    const port = Number(env.ORCHESTRATION_PORT ?? 4111);
    const timeoutMs = Number(env.ORCHESTRATION_TIMEOUT_MS ?? 420000);
    const base = new URL(env.FASTAPI_BASE_URL ?? 'http://127.0.0.1:8000');
    const origin = new URL(env.CORS_ORIGIN ?? 'http://localhost:5173');
    if (!Number.isInteger(port) || port < 1024 || port > 65535 || !Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 600000 ||
        !['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.pathname !== '/' || base.search || base.hash ||
        Number(base.port) === port || !['http:', 'https:'].includes(origin.protocol) || origin.origin !== origin.href.slice(0, -1)) throw new Error();
    return { port, timeoutMs, baseUrl: base.origin, allowedOrigin: origin.origin };
  } catch {
    throw new Error('Invalid orchestration configuration. Use a backend origin, a browser origin and bounded port/timeout values.');
  }
}
