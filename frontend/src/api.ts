export interface Competitor {
  product_name: string | null;
  listed_price: number | null;
  currency: string | null;
  merchant: string | null;
  product_url: string | null;
  source: string;
  retrieved_at: string;
  features: string[] | null;
}

export async function searchCompetitors(productName: string): Promise<Competitor[]> {
  const response = await fetch('/api/competitors/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_name: productName, market: 'India', currency: 'INR', max_results: 5 }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Search is unavailable. Please try again.');
  return data.competitors;
}

export interface Finding { text: string; source_ids: string[] }
export interface ProductAttributes {
  category: string | null; capacity_ml: string | null; material: string | null;
  brand: string | null; model: string | null; conflicts?: string[];
}
export interface StageTiming {
  stage: string; elapsed_ms: number; outcome: string;
  total_ms: number | null; load_ms: number | null; prompt_eval_ms: number | null; generation_ms: number | null;
  prompt_tokens: number | null; generated_tokens: number | null; tokens_per_second: number | null;
}
export interface Intelligence {
  evidence_quality?: { sample_size: number; band: 'none' | 'single' | 'small' | 'descriptive'; explanation: string; source_ids: string[] } | null;
  recommendation_safety?: { policy_version: string; status: 'passed' | 'adjusted'; replaced_count: number; reason_codes: string[]; message: string } | null;
  model: string;
  market?: string | null;
  queries: string[];
  listings: (Competitor & { id: string; discovery_query: string; duplicate_of: string | null;
    attributes: ProductAttributes; comparability: { category: 'identical' | 'variant' | 'comparable_alternative' | 'alternative' | 'uncertain'; eligible: boolean; reason: string } })[];
  duplicate_count: number;
  caveats: string[];
  persistence?: { status: 'saved' | 'disabled' | 'error'; report_id: string | null; saved_at: string | null; message: string; elapsed_ms: number | null };
  seller_attributes: ProductAttributes;
  market_observations: { price_count: number; minimum: string | null; median: string | null; maximum: string | null; source_ids: string[] };
  performance: { request_id: string; total_ms: number; stages: StageTiming[] } | null;
  pricing: {
    currency: string; selling_price: string; cost: string | null;
    gross_profit: string | null; gross_margin_percent: string | null;
    comparable_price_count: number; minimum: string | null; median: string | null; maximum: string | null;
    benchmark_status: 'sufficient' | 'insufficient'; benchmark_message: string; minimum_required: number;
    comparisons: { source_id: string; listed_price: string; seller_minus_listing: string; seller_difference_percent: string | null }[];
  };
  report: {
    market_overview: Finding;
    competitive_advantages: Finding[];
    competitive_threats: Finding[];
    pricing_observations: Finding[];
    recommendations: Finding[];
    classifications: { source_id: string; category: 'identical' | 'variant' | 'alternative' | 'uncertain'; reason: string }[];
  };
}

export interface ReportSummary {
  id: string; created_at: string; product_name: string; currency: string; selling_price: string;
  listing_count: number; comparable_price_count: number; benchmark_status: 'sufficient' | 'insufficient';
  model: string; analysis_ms: number | null;
}
export interface SavedReport {
  id: string; created_at: string; schema_version: number;
  seller_inputs: { product_name: string; selling_price: string; cost: string | null; market: string; currency: string; max_results: number; seller_attributes: ProductAttributes | null };
  intelligence: Intelligence;
}

async function getSavedData<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Report history is currently unavailable.');
  return data;
}
export const listReports = (offset = 0, signal?: AbortSignal) => getSavedData<{ reports: ReportSummary[]; next_offset: number | null }>(`/api/reports?limit=10&offset=${offset}`, signal);
export const getReport = (id: string, signal?: AbortSignal) => getSavedData<SavedReport>(`/api/reports/${encodeURIComponent(id)}`, signal);

export interface PricingPrediction {
  status: 'predicted' | 'insufficient_data' | 'unavailable'; reason: string; experimental: boolean;
  predicted_price: number | null; currency: string; model: string; sample_count: number; minimum_samples: number;
  observation_start: string | null; observation_end: string | null; limitations: string[];
  sources: { observation_id: string; source_product_id: string | null; product_url: string; retrieved_at: string }[];
}

export async function predictPrice(attributes: ProductAttributes, currency: string, market: string, signal?: AbortSignal): Promise<PricingPrediction> {
  const response = await fetch('/api/pricing/predict', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ attributes, currency, market, allow_cloud_processing: true }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Prediction request failed. Existing intelligence remains available.');
  return data;
}

export async function analyzeCompetitors(productName: string, sellingPrice: string, cost: string, attributes?: Partial<ProductAttributes>): Promise<Intelligence> {
  const response = await fetch('/api/intelligence', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_name: productName, selling_price: sellingPrice, cost: cost || null, seller_attributes: attributes }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Analysis failed. Check your inputs and the API server.');
  return data;
}
