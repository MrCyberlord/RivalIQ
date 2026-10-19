import { useEffect, useState, type FormEvent } from 'react';
import { analyzeCompetitors, type Intelligence } from '../api';
import IntelligenceReportView from './IntelligenceReportView';
import { runGuidedAnalysis, type GuidedRun } from '../guided';
import GuidedAnalysis from './GuidedAnalysis';

export default function IntelligencePanel({ onSaved }: { onSaved?: () => void }) {
  const [product, setProduct] = useState('');
  const [price, setPrice] = useState('');
  const [cost, setCost] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<Intelligence | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [brand, setBrand] = useState('');
  const [capacity, setCapacity] = useState('');
  const [material, setMaterial] = useState('');
  const [category, setCategory] = useState('');
  const [guided, setGuided] = useState<GuidedRun | null>(null);

  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setElapsed(0); setLoading(true); setError(''); setData(null); setGuided(null);
    const useGuided = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'guided';
    const attributes = {
      brand: brand.trim() || null, capacity_ml: capacity || null, material: material || null, category: category || null,
    };
    try { const result = useGuided
      ? (await runGuidedAnalysis(product.trim(), price, cost, attributes, setGuided)).result!.report
      : await analyzeCompetitors(product.trim(), price, cost, attributes);
      setData(result); if (result.persistence?.status === 'saved') onSaved?.(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to reach the intelligence API.'); }
    finally { setLoading(false); }
  }

  return <section className="intelligence" aria-labelledby="intelligence-heading">
    <p className="eyebrow">FROM LISTINGS TO YOUR NEXT MOVE</p>
    <h2 id="intelligence-heading">Competitor intelligence</h2>
    <p className="note">Explore similar products and alternatives with local Gemma analysis. AI conclusions are estimates, not verified facts.</p>
    <form onSubmit={submit} className="search-panel intelligence-form">
      <div className="intelligence-inputs">
        <div><label htmlFor="seller-product">Your product</label><input id="seller-product" required maxLength={200} pattern=".*\S.*" placeholder="Brand, model or descriptive product name" value={product} onChange={e => setProduct(e.target.value)} disabled={loading} /></div>
        <div><label htmlFor="seller-price">Selling price (INR)</label><input id="seller-price" type="number" required min="0.01" max="999999999999.99" step="0.01" placeholder="799.00" value={price} onChange={e => setPrice(e.target.value)} disabled={loading} /></div>
        <div><label htmlFor="seller-cost">Cost (INR, optional)</label><input id="seller-cost" type="number" min="0" max="999999999999.99" step="0.01" placeholder="500.00" value={cost} onChange={e => setCost(e.target.value)} disabled={loading} /></div>
      </div>
      <details className="seller-details"><summary>Optional product attributes for more precise comparisons</summary>
        <p>Provide only specifications you know. Unknown attributes can prevent a reliable comparison.</p>
        <div className="intelligence-inputs">
          <div><label htmlFor="seller-brand">Brand</label><input id="seller-brand" maxLength={80} value={brand} onChange={e => setBrand(e.target.value)} disabled={loading} /></div>
          <div><label htmlFor="seller-capacity">Capacity (ml)</label><input id="seller-capacity" type="number" min="0.01" max="10000000" step="0.01" value={capacity} onChange={e => setCapacity(e.target.value)} disabled={loading} /></div>
          <div><label htmlFor="seller-material">Material</label><select id="seller-material" value={material} onChange={e => setMaterial(e.target.value)} disabled={loading}><option value="">Unknown</option>{['stainless steel', 'plastic', 'glass', 'copper', 'aluminium', 'ceramic'].map(v => <option key={v}>{v}</option>)}</select></div>
          <div><label htmlFor="seller-category">Category</label><select id="seller-category" value={category} onChange={e => setCategory(e.target.value)} disabled={loading}><option value="">Unknown</option>{['bottle', 'flask', 'mug', 'container', 'headphones', 'earbuds', 'backpack', 'phone'].map(v => <option key={v}>{v}</option>)}</select></div>
        </div>
      </details>
      <button disabled={loading}>{loading ? 'Discovering, analyzing and saving…' : 'Generate intelligence report →'}</button>
      <button type="submit" name="analysis-mode" value="guided" disabled={loading}>Run guided analysis</button>
      <p>Guided analysis requires the optional local Mastra service. Both actions use the same FastAPI analysis. No automatic fallback or price prediction runs.</p>
      <p>India · Two shopping searches, up to 5 listings each · Local analysis may take several minutes</p>
    </form>
    <div aria-live="polite" aria-busy={loading}>
      {loading && <div className="analysis-loading" role="status"><span className="loading-dot" /><div><strong>Analysis in progress · {elapsed}s elapsed</strong><p>Discovering listings, checking comparability, preparing your report and saving when available. Local Gemma can take several minutes. Timings appear when the report is ready.</p></div></div>}
      {error && <p className="error" role="alert">{error} Check saved report history before retrying. Product search and direct analysis remain available.</p>}
    </div>
    {guided && <GuidedAnalysis run={guided} />}
    {data && <IntelligenceReportView data={data} />}

  </section>;
}
