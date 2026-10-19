export const attrs = { category: 'bottle', capacity_ml: '500', material: 'steel', brand: null, model: null, conflicts: [] };
export const seller = { product_name: 'Test bottle', selling_price: '150', seller_attributes: { category: 'bottle' } };
export function reportFixture() {
  const finding = { text: 'Check this listing before changing the offer.', source_ids: ['L1'] };
  return {
    model: 'gemma3:4b', market: 'India', queries: ['test'], duplicate_count: 0, seller_attributes: attrs,
    market_observations: { price_count: 1, minimum: '100', median: '100', maximum: '100', source_ids: ['L1'] }, performance: null,
    listings: [{ id: 'L1', product_name: 'Test bottle', source: 'serpapi_google_shopping', retrieved_at: '2026-10-19T00:00:00Z', features: null,
      attributes: attrs, discovery_query: 'test', product_url: 'https://shop.example/item', merchant: 'Test merchant', duplicate_of: null, currency: 'INR', listed_price: 100,
      comparability: { category: 'comparable_alternative', eligible: true, reason: 'Explicit matching attributes' } }],
    pricing: { currency: 'INR', selling_price: '150', cost: null, gross_profit: null, gross_margin_percent: null,
      benchmark_status: 'insufficient', benchmark_message: 'Insufficient comparable products.', comparable_price_count: 1, minimum_required: 2,
      minimum: null, median: null, maximum: null, comparisons: [{ source_id: 'L1', listed_price: '100', seller_minus_listing: '50', seller_difference_percent: '50' }] },
    report: { market_overview: finding, competitive_advantages: [], competitive_threats: [finding], pricing_observations: [finding], recommendations: [finding, finding, finding], classifications: [{ source_id: 'L1', category: 'alternative', reason: 'AI estimate' }] },
    persistence: { status: 'disabled', report_id: null, saved_at: null, elapsed_ms: null, message: 'Saving unavailable' }, caveats: ['Unverified AI analysis'],
  };
}
