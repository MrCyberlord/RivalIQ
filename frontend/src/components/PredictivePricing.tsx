import { useEffect, useRef, useState } from 'react';
import { predictPrice, type PricingPrediction, type ProductAttributes } from '../api';

export default function PredictivePricing({ attributes, currency, market }: { attributes: ProductAttributes; currency: string; market?: string | null }) {
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PricingPrediction | null>(null);
  const [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const complete = Boolean(market) && ['brand', 'category', 'capacity_ml', 'material'].every(key => attributes[key as keyof ProductAttributes] != null)
    && !attributes.conflicts?.length;

  async function predict() {
    if (!market) return;
    const active = new AbortController(); controller.current = active;
    setLoading(true); setError(''); setResult(null);
    try { const value = await predictPrice(attributes, currency, market, active.signal); if (!active.signal.aborted) setResult(value); }
    catch (cause) { if (!active.signal.aborted) setError(cause instanceof Error ? cause.message : 'Prediction unavailable.'); }
    finally { if (!active.signal.aborted) setLoading(false); }
  }

  return <section className="predictive-pricing" aria-label="Experimental predictive pricing">
    <div className="report-heading"><h3>Predictive pricing</h3><span className="badge">Experimental · Hosted TabPFN</span></div>
    <p>This is separate from observed-price benchmarks and Gemma recommendations. It estimates a listing price from real comparable observations; it is not a verified fair value, optimal selling price, demand forecast or profit guarantee.</p>
    <p className="note">Requires at least 30 independently identified products from 3 brands, including 5 from your brand, with matching category, capacity, material, market and currency in the last 90 days. Repeated snapshots do not increase the sample count.</p>
    {!complete && <p className="benchmark-warning">This report lacks explicit brand, category, capacity, material or market, or has conflicting attributes. Generate a new report with known product attributes before requesting a prediction.</p>}
    <label className="cloud-consent"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={loading} /><span>I agree to send structured public product attributes, observation age/source engine and observed competitor prices to Prior Labs for hosted processing. Provider retention terms apply. Queries, descriptions, URLs, retailer names, my selling price and cost are excluded.</span></label>
    <button disabled={!complete || !consent || loading} onClick={predict}>{loading ? 'Checking history and requesting prediction…' : 'Request experimental price prediction'}</button>
    <div aria-live="polite" aria-busy={loading}>
      {loading && <p className="note">The data gate runs before any hosted inference. Existing intelligence remains available while this request runs.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {result && <div className="prediction-result">
        <h4>{result.status === 'predicted' ? `Experimental estimate: ${result.currency} ${result.predicted_price?.toLocaleString()}` : result.status === 'insufficient_data' ? 'Insufficient independent data' : 'Prediction unavailable'}</h4>
        <p>{result.reason}</p><p className="note">{result.sample_count} independent products · Minimum {result.minimum_samples} · {result.model}</p>
        {result.observation_start && result.observation_end && <p className="note">Observed {new Date(result.observation_start).toLocaleString()} to {new Date(result.observation_end).toLocaleString()}.</p>}
        <details><summary>Limitations and observation sources</summary><ul>{result.limitations.map(text => <li key={text}>{text}</li>)}</ul>{result.sources.length > 0 && <ul>{result.sources.map(source => <li key={source.observation_id}><a href={source.product_url} target="_blank" rel="noreferrer">Observed listing ↗</a> · {new Date(source.retrieved_at).toLocaleString()}</li>)}</ul>}</details>
      </div>}
    </div>
  </section>;
}
