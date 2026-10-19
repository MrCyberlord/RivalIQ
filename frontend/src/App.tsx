import { useState, type FormEvent } from 'react';
import { searchCompetitors, type Competitor } from './api';
import IntelligencePanel from './components/IntelligencePanel';
import ReportHistory from './components/ReportHistory';

export default function App() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Competitor[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [historyRefresh, setHistoryRefresh] = useState(0);

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true); setError(''); setResults(null);
    try { setResults(await searchCompetitors(query.trim())); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to reach the API.'); }
    finally { setLoading(false); }
  }

  return <div className="page">
    <header><a className="brand" href="/" aria-label="RivalIQ home"><span className="mark">R</span>Rival<span>IQ</span></a><span className="edition">Hacktoberfest · Week 2</span></header>
    <main>
      <section className="hero">
        <p className="eyebrow"><span /> BUILT FOR INDEPENDENT SELLERS</p>
        <h1>Your next move starts<br />with <em>market clarity.</em></h1>
        <p className="intro">Meet RivalIQ. Discover competing products, compare listed prices, and see who’s selling — all from one simple search.</p>
        <form onSubmit={search} className="search-panel">
          <label htmlFor="product">What do you sell?</label>
          <div className="search-row"><input id="product" value={query} onChange={e => setQuery(e.target.value)} placeholder="e.g. stainless steel water bottle" required maxLength={200} pattern=".*\S.*" disabled={loading} /><button disabled={loading}>{loading ? 'Searching…' : 'Find competitors →'}</button></div>
          <p>India market <span>·</span> Up to 5 Google Shopping listings <span>·</span> No account needed</p>
        </form>
        <div aria-live="polite" aria-busy={loading} className="results">
          {error && <p role="alert" className="error">{error}</p>}
          {results?.length === 0 && <p>No listings found. Try a more specific product name.</p>}
          {!!results?.length && <><h2>Listings from your search</h2><p className="note">Prices are shown as reported. Missing details are marked unavailable.</p><ul>{results.map((item, index) => <li key={`${item.product_url}-${index}`}><div><h3>{item.product_name ?? 'Product name unavailable'}</h3><p>{item.merchant ?? 'Merchant unavailable'}</p>{item.features && <p>{item.features.join(' · ')}</p>}<small>{item.source} · Retrieved {new Date(item.retrieved_at).toLocaleString()}</small></div><div className="listing-price"><strong>{item.listed_price === null ? 'Price unavailable' : `${item.currency ?? 'Currency unavailable'} ${item.listed_price.toLocaleString()}`}</strong>{item.product_url && <a href={item.product_url} target="_blank" rel="noreferrer">View listing ↗</a>}</div></li>)}</ul></>}
        </div>
      </section>
      <IntelligencePanel onSaved={() => setHistoryRefresh(v => v + 1)} />
      <ReportHistory refreshToken={historyRefresh} />
      <section className="steps" aria-label="How it works">{[['01', 'Discover your competition', 'Search a product to find relevant shopping listings in your market.'], ['02', 'See the details', 'Compare reported prices, merchants, and available product features.'], ['03', 'Make an informed move', 'Follow source links and use real market context to guide your next decision.']].map(([n, title, copy]) => <article key={n}><span>{n}</span><h2>{title}</h2><p>{copy}</p></article>)}</section>
    </main>
    <footer><span>RivalIQ © {new Date().getFullYear()}</span><span>Experimental pricing intelligence · Milestone 4</span></footer>
  </div>;
}
