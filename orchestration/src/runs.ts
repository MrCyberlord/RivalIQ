import { Mastra } from '@mastra/core/mastra';
import { randomUUID } from 'node:crypto';
import { makeWorkflow, WorkflowError } from './workflow.js';
import { sellerSchema, stepIds, type StepStatus } from './contracts.js';

export type RunResult = { run_id: string; status: 'running' | 'success' | 'failed'; steps: StepStatus[]; duration_ms: number | null; upstream_calls: number;
  result?: { report: unknown; action_brief: unknown }; error?: { code: string; message: string }; expires_at: string };
export class RunManager {
  private runs = new Map<string, RunResult>();
  constructor(private options: { baseUrl: string; timeoutMs: number; fetcher?: typeof fetch; log?: (entry: object) => void; ttlMs?: number }) {}
  get(id: string) { this.prune(); return this.runs.get(id); }
  private prune() { for (const [id, run] of this.runs) if (run.status !== 'running' && Date.parse(run.expires_at) <= Date.now()) this.runs.delete(id); }
  async start(input: unknown) {
    const seller = sellerSchema.parse(input); this.prune();
    if ([...this.runs.values()].filter(r => r.status === 'running').length >= 2 || this.runs.size >= 50)
      throw new WorkflowError('busy', 'The local workflow service is busy. Try later.');
    const runId = randomUUID();
    const record: RunResult = { run_id: runId, status: 'running', duration_ms: null, upstream_calls: 0,
      expires_at: new Date(Date.now() + (this.options.ttlMs ?? 600000) + this.options.timeoutMs).toISOString(),
      steps: stepIds.map(id => ({ id, status: 'pending', duration_ms: null })) };
    this.runs.set(runId, record);
    const started = performance.now();
    const workflow = makeWorkflow({ ...this.options,
      fetcher: async (...args) => { record.upstream_calls++; return (this.options.fetcher ?? fetch)(...args); },
      onError: error => { record.error = { code: error.code, message: error.message }; },
      onStep: step => { record.steps = record.steps.map(s => s.id === step.id ? step : s); },
    });
    // No storage, exporters, agents, hosted services, or automatic recovery. Disable SDK logs
    // because error payloads may contain upstream request data.
    new Mastra({ workflows: { guided: workflow }, logger: false });
    const execute = async () => {
      try {
        const run = await workflow.createRun({ runId });
        const result = await run.start({ inputData: seller });
        if (result.status !== 'success') throw new Error('workflow_failed');
        record.result = result.result; record.status = 'success';
      } catch {
        record.status = 'failed'; record.error ??= { code: 'workflow_failed', message: 'Guided analysis failed. Check history before retrying; the direct analysis path remains available.' };
        record.steps = record.steps.map(s => s.status === 'pending' ? { ...s, status: 'skipped' } : s.status === 'running' ? { ...s, status: 'failed' } : s);
      } finally {
        record.duration_ms = Math.round(performance.now() - started);
        record.expires_at = new Date(Date.now() + (this.options.ttlMs ?? 600000)).toISOString();
        this.options.log?.({ event: 'workflow_complete', run_id: runId, status: record.status, duration_ms: record.duration_ms,
          error_code: record.error?.code, upstream_calls: record.upstream_calls, steps: record.steps });
      }
    };
    void execute();
    return record;
  }
}
