import { type Finding, type Intelligence } from '../api';
import PredictivePricing from './PredictivePricing';

function Evidence({ finding, prefix }: { finding: Finding; prefix: string }) {
  return <p>{finding.text} <span className="citations">{finding.source_ids.map(id => <a key={id} href={`#${prefix}-${id}`} aria-label={`Supporting listing ${id}`}>[{id}]</a>)}</span></p>;
}

const labels = { identical: 'Identical product (estimated)', variant: 'Product variant (estimated)', comparable_alternative: 'Comparable alternative (estimated)', alternative: 'Broader alternative', uncertain: 'Uncertain match' };

export default function IntelligenceReportView({ data, idPrefix = 'intelligence' }: { data: Intelligence; idPrefix?: string }) {
  const money = (value: string | null) => value === null ? 'Unavailable' : `${data.pricing.currency} ${value}`;
  return <div className="intelligence-report">
      {data.persistence && <p className={data.persistence.status === 'saved' ? 'save-status' : 'benchmark-warning'} role="status">{data.persistence.message}{data.persistence.status === 'saved' && data.persistence.saved_at ? ` Saved ${new Date(data.persistence.saved_at).toLocaleString()}.` : ''}</p>}
      <div className="report-heading"><h3>Your intelligence report</h3><span className="badge">{data.model} · Unverified AI analysis</span></div>
      <div className="report-card"><h3>Broader market overview</h3><Evidence prefix={idPrefix} finding={data.report.market_overview} /></div>
      <p className="note">Your stated/extracted attributes: {Object.entries(data.seller_attributes).filter(([key, value]) => key !== 'conflicts' && value !== null).map(([key, value]) => `${key === 'capacity_ml' ? 'capacity (ml)' : key}: ${value}`).join(' · ') || 'Unknown'}</p>
      {!!data.seller_attributes.conflicts?.length && <p className="error">Conflicting seller attributes: {data.seller_attributes.conflicts.join(', ')}. Resolve these before relying on comparisons.</p>}
      <h3>Primary pricing · Attribute-matched offers</h3><p className="note">Calculated in Python. Matching stated specifications are estimates of comparability, not verification of identity or quality.</p>
      <p className={data.pricing.benchmark_status === 'insufficient' ? 'benchmark-warning' : 'note'}>{data.pricing.benchmark_message}</p>
      <dl className="price-metrics">
        <div><dt>Your price</dt><dd>{money(data.pricing.selling_price)}</dd></div>
        <div><dt>Comparable median</dt><dd>{money(data.pricing.median)}</dd></div>
        <div><dt>Comparable minimum / maximum</dt><dd>{money(data.pricing.minimum)} / {money(data.pricing.maximum)}</dd></div>
        <div><dt>Gross profit / margin</dt><dd>{money(data.pricing.gross_profit)} / {data.pricing.gross_margin_percent === null ? 'Unavailable' : `${data.pricing.gross_margin_percent}%`}</dd></div>
      </dl>
      <p className="note">{data.pricing.comparable_price_count} comparable offers with usable prices · Minimum {data.pricing.minimum_required} required · {data.duplicate_count} duplicate observations excluded</p>
      <article className="report-card"><h3>Broader market observations · Not a seller benchmark</h3><p>{data.market_observations.price_count} same-currency listings, including variants and uncertain matches. Median: {money(data.market_observations.median)}. Range: {money(data.market_observations.minimum)} to {money(data.market_observations.maximum)}.</p><p className="note">Do not use these figures to infer that your product is overpriced or underpriced. Sources: {data.market_observations.source_ids.map(id => <a className="market-citation" key={id} href={`#${idPrefix}-${id}`}>[{id}] </a>)}</p></article>
      <div className="report-grid">{([
        ['Competitive advantages', data.report.competitive_advantages],
        ['Competitive threats', data.report.competitive_threats],
        ['Pricing observations', data.report.pricing_observations],
      ] as [string, Finding[]][]).map(([title, findings]) => <article className="report-card" key={title}><h3>{title}</h3>{findings.length ? findings.map((finding, i) => <Evidence prefix={idPrefix} key={i} finding={finding} />) : <p>Insufficient evidence to identify any.</p>}</article>)}</div>
      <article className="report-card"><h3>Three actions for your product</h3>
        {data.evidence_quality && <p className="note">{data.evidence_quality.explanation}</p>}
        {data.recommendation_safety && <p className="note">{data.recommendation_safety.message}</p>}
        <ol>{data.report.recommendations.map((finding, i) => <li key={i}><Evidence prefix={idPrefix} finding={finding} /></li>)}</ol></article>
      <PredictivePricing key={data.performance?.request_id ?? data.persistence?.report_id ?? data.queries.join('|')}
        attributes={data.seller_attributes} currency={data.pricing.currency} market={data.market} />
      <h3>Sources and attribute-rule classifications</h3>
      <p className="note">Queries: {data.queries.join(' · ')}. Duplicate observations retain their original merchant, price and URL.</p>
      <div className="source-list">{data.listings.map(item => {
        const comparison = data.pricing.comparisons.find(c => c.source_id === item.id);
        return <article className="source-card" key={item.id} id={`${idPrefix}-${item.id}`}>
          <div className="source-heading"><h4>{item.id} · {item.product_name ?? 'Product name unavailable'}</h4><span className="badge">{labels[item.comparability.category]}</span></div>
          {item.duplicate_of && <p className="duplicate">Duplicate of <a href={`#${idPrefix}-${item.duplicate_of}`}>{item.duplicate_of}</a> · Excluded from calculations</p>}
          <p>{item.comparability.reason} {item.comparability.eligible && !item.duplicate_of ? 'Attribute-eligible; price requires known matching currency.' : 'Excluded from primary pricing.'}</p>
          <p className="note">Stated attributes: {Object.entries(item.attributes).filter(([key, value]) => key !== 'conflicts' && value !== null).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'Unknown'}</p>
          <p><strong>{item.listed_price === null ? 'Price unavailable' : `${item.currency ?? 'Currency unknown'} ${item.listed_price.toLocaleString()}`}</strong> · {item.merchant ?? 'Merchant unavailable'}</p>
          {comparison && <p>Your price minus listing: {money(comparison.seller_minus_listing)} ({comparison.seller_difference_percent === null ? 'percentage unavailable' : `${comparison.seller_difference_percent}%`})</p>}
          {item.features && <p>Reported features: {item.features.join(' · ')}</p>}
          <p>{item.product_url ? <a href={item.product_url} target="_blank" rel="noreferrer">View original listing ↗</a> : 'Source URL unavailable'}</p>
          <small>{item.source} · Retrieved {new Date(item.retrieved_at).toLocaleString()} · Query: {item.discovery_query}</small>
        </article>;
      })}</div>
      {data.performance && <details className="performance"><summary>Performance · {(data.performance.total_ms / 1000).toFixed(1)}s total</summary>
        <p className="note">Server analysis time; excludes browser/network transfer. Ollama timings come from the model server; missing metadata stays unavailable.</p>
        <div className="timing-table"><table><thead><tr><th>Stage</th><th>Wall time</th><th>Model load</th><th>Prompt eval</th><th>Generation</th><th>Tokens/s</th></tr></thead><tbody>{data.performance.stages.map(stage => <tr key={stage.stage}><th>{stage.stage.replaceAll('_', ' ')}</th><td>{(stage.elapsed_ms / 1000).toFixed(2)}s</td>{[stage.load_ms, stage.prompt_eval_ms, stage.generation_ms].map((ms, i) => <td key={i}>{ms === null ? '—' : `${(ms / 1000).toFixed(2)}s`}</td>)}<td>{stage.tokens_per_second ?? '—'}</td></tr>)}</tbody></table></div>
      </details>}
      <aside className="report-caveats"><h3>Scope and limitations</h3><ul>{data.caveats.map(caveat => <li key={caveat}>{caveat}</li>)}</ul></aside>
    </div>;
}
