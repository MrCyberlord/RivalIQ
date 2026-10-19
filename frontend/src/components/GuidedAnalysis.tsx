import type { GuidedRun } from '../guided';
const labels: Record<string, string> = { 'accept-seller': 'Validate seller details', 'fastapi-intelligence': 'Generate and save report in FastAPI', 'inspect-evidence': 'Check evidence and comparability', 'seller-action-brief': 'Assemble seller action brief' };
export default function GuidedAnalysis({ run }: { run: GuidedRun }) {
  const brief = run.result?.action_brief;
  return <section className="guided-result" aria-labelledby="guided-heading">
    <h3 id="guided-heading">Guided analysis workflow</h3>
    <p className="note">Run {run.run_id} · {run.status}{run.duration_ms !== null ? ` · ${(run.duration_ms / 1000).toFixed(2)}s` : ''}</p>
    <ol className="workflow-steps" aria-live="polite">{run.steps.map(step => <li key={step.id}><strong>{labels[step.id] ?? step.id}</strong><span>{step.status}{step.duration_ms !== null ? ` · ${(step.duration_ms / 1000).toFixed(2)}s` : ''}</span></li>)}</ol>
    {brief && <><h3>Seller action brief</h3>
      <h4>What the data shows</h4>
      <p><strong>Your current price: {brief.seller_current_price.currency} {brief.seller_current_price.amount}</strong></p>
      <p>{brief.benchmark_available ? 'Primary comparison available' : 'Insufficient comparable evidence'} · {brief.comparable_count} comparable prices</p>
      <p>{brief.benchmark_message}</p><p>{brief.broader_market_note}</p>
      {brief.benchmark_available && <p>Comparable offers · {brief.seller_current_price.currency} {brief.comparable_evidence.minimum}–{brief.comparable_evidence.maximum} · Median {brief.comparable_evidence.median}</p>}
      <p>Comparable evidence: {brief.comparable_evidence.source_ids.length ? brief.comparable_evidence.source_ids.map(id => {
        const source = brief.sources.find(s => s.source_id === id);
        return source ? <a key={id} href={source.url} target="_blank" rel="noreferrer">{id} </a> : <span key={id}>{id} · URL unavailable </span>;
      }) : 'No eligible offers with usable prices.'}</p>
      <p><strong>Report saving: {brief.save_status}</strong>{brief.report_id ? ` · ${brief.report_id}` : ''}</p>
      <h4>What the seller could do</h4>
      <p className="note">{brief.recommendation_safety_message} The workflow maps the validated report; it does not verify AI conclusions.</p>
      <ol>{brief.recommendations.map((r, i) => <li key={i}>{r.text}<div>{r.source_ids.map(id => {
        const source = brief.sources.find(s => s.source_id === id);
        return source ? <a key={id} href={source.url} target="_blank" rel="noreferrer">{id}{source.merchant ? ` · ${source.merchant}` : ''} </a> : <span key={id}>{id} · source URL unavailable </span>;
      })}</div></li>)}</ol>
      <h4>What remains uncertain</h4>
      <p>{brief.evidence_confidence}</p>
      <ul>{brief.suggested_next_steps.map(step => <li key={step}>{step}</li>)}</ul>
      {brief.warnings.map(w => <p className="note" key={w}>{w}</p>)}
      <details><summary>Brief limitations</summary><ul>{brief.limitations.map((v, i) => <li key={i}>{v}</li>)}</ul></details>
    </>}
  </section>;
}
