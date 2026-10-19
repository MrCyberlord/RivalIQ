import { useEffect, useRef, useState } from 'react';
import { getReport, listReports, type ReportSummary, type SavedReport } from '../api';
import IntelligenceReportView from './IntelligenceReportView';

export default function ReportHistory({ refreshToken }: { refreshToken: number }) {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<SavedReport | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState('');
  const openRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    listReports(offset, controller.signal).then(data => { if (!controller.signal.aborted) { setReports(data.reports); setNextOffset(data.next_offset); } })
      .catch(cause => { if (!controller.signal.aborted) { setReports([]); setNextOffset(null); setError(cause instanceof Error ? cause.message : 'History unavailable.'); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, refresh, refreshToken]);
  useEffect(() => () => openRequest.current?.abort(), []);

  async function reopen(id: string) {
    openRequest.current?.abort();
    const controller = new AbortController(); openRequest.current = controller;
    setOpening(true); setOpenError(''); setOpened(null);
    try { const report = await getReport(id, controller.signal); if (!controller.signal.aborted) setOpened(report); }
    catch (cause) { if (!controller.signal.aborted) setOpenError(cause instanceof Error ? cause.message : 'Unable to open report.'); }
    finally { if (!controller.signal.aborted) setOpening(false); }
  }

  return <section className="intelligence report-history" aria-labelledby="history-heading">
    <div className="report-heading"><div><p className="eyebrow">YOUR RESEARCH, SAVED</p><h2 id="history-heading">Report history</h2></div><button disabled={loading} onClick={() => { setOffset(0); setRefresh(v => v + 1); }}>Refresh history</button></div>
    <p className="note">Reopen saved intelligence without running another shopping search or AI analysis. Reports show the data and prices captured at their original retrieval time.</p>
    <div aria-live="polite" aria-busy={loading}>{loading && <p>Loading saved reports…</p>}{error && <p className="benchmark-warning">{error} New analysis remains available above.</p>}{!loading && !error && reports.length === 0 && <p>No saved reports yet. Completed analyses are saved when MongoDB is available.</p>}</div>
    <div className="history-grid">{reports.map(report => <article className="report-card" key={report.id}><h3>{report.product_name}</h3><p className="note">{new Date(report.created_at).toLocaleString()} · {report.model}</p><p>{report.currency} {report.selling_price} · {report.listing_count} listings · {report.comparable_price_count} comparable offers</p><p className="note">{report.benchmark_status === 'insufficient' ? 'Insufficient comparable offers for a benchmark' : 'Comparable pricing available'}{report.analysis_ms === null ? '' : ` · Original analysis ${(report.analysis_ms / 1000).toFixed(1)}s`}</p><button disabled={opening} onClick={() => reopen(report.id)}>Open saved report</button></article>)}</div>
    <nav className="history-pagination" aria-label="Report history pages"><button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>Previous</button><button disabled={loading || nextOffset === null} onClick={() => { if (nextOffset !== null) setOffset(nextOffset); }}>Next</button></nav>
    <div aria-live="polite" aria-busy={opening}>{opening && <p>Opening the saved report…</p>}{openError && <p role="alert" className="error">{openError}</p>}</div>
    {opened && <div className="opened-report"><div className="report-heading"><h3>Saved report · {opened.seller_inputs.product_name}</h3><button onClick={() => setOpened(null)}>Close report</button></div><p className="note">Saved {new Date(opened.created_at).toLocaleString()} · Selling price {opened.seller_inputs.currency} {opened.seller_inputs.selling_price} · Cost {opened.seller_inputs.cost ?? 'not provided'} · {opened.seller_inputs.market}</p><IntelligenceReportView data={opened.intelligence} idPrefix="history-report" /></div>}
  </section>;
}
