import { z } from 'zod';

const short = z.string().trim().min(1).max(80).nullable().optional();
const money = z.union([z.string().regex(/^\d{1,12}(\.\d{1,2})?$/), z.number().finite().nonnegative().max(999999999999.99).refine(v => Number.isInteger(v * 100) || Math.abs(v * 100 - Math.round(v * 100)) < 0.001)]);
export const sellerSchema = z.object({
  product_name: z.string().trim().min(1).max(200),
  selling_price: money.refine(v => Number(v) > 0), cost: money.nullable().optional(),
  market: z.enum(['India', 'United States', 'United Kingdom', 'Canada', 'Australia']).default('India'),
  currency: z.enum(['INR', 'USD', 'GBP', 'CAD', 'AUD']).default('INR'),
  max_results: z.number().int().min(1).max(6).default(5),
  seller_attributes: z.object({ category: short, brand: short, material: short, model: short,
    capacity_ml: z.union([z.string().regex(/^\d+(\.\d+)?$/), z.number()]).refine(v => Number(v) > 0 && Number(v) <= 10000000).nullable().optional(),
  }).strict().nullable().optional(),
}).strict();
const finding = z.object({ text: z.string().min(1), source_ids: z.array(z.string()).min(1) });
const decimal = z.string().refine(v => v.trim() !== '' && Number.isFinite(Number(v)));
const attributes = z.object({ category: z.string().nullable(), capacity_ml: decimal.nullable(), material: z.string().nullable(), brand: z.string().nullable(), model: z.string().nullable(), conflicts: z.array(z.string()) }).passthrough();
export const reportSchema = z.object({
  model: z.string(), market: z.string().nullable().optional(), queries: z.array(z.string()), duplicate_count: z.number().int().nonnegative(),
  seller_attributes: attributes,
  market_observations: z.object({ price_count: z.number().int().nonnegative(), minimum: decimal.nullable(), median: decimal.nullable(), maximum: decimal.nullable(), source_ids: z.array(z.string()) }).passthrough(),
  performance: z.object({ request_id: z.string(), total_ms: z.number().finite(), stages: z.array(z.object({ stage: z.string(), elapsed_ms: z.number().finite(), outcome: z.string(), total_ms: z.number().nullable(), load_ms: z.number().nullable(), prompt_eval_ms: z.number().nullable(), generation_ms: z.number().nullable(), prompt_tokens: z.number().nullable(), generated_tokens: z.number().nullable(), tokens_per_second: z.number().nullable() }).passthrough()) }).nullable(),
  listings: z.array(z.object({ id: z.string(), product_url: z.string().nullable(), merchant: z.string().nullable(),
    product_name: z.string().nullable(), source: z.string(), retrieved_at: z.string(), features: z.array(z.string()).nullable(), attributes,
    discovery_query: z.string(), duplicate_of: z.string().nullable(), currency: z.string().nullable(), listed_price: z.number().finite().nullable(),
    comparability: z.object({ category: z.enum(['identical', 'variant', 'comparable_alternative', 'alternative', 'uncertain']), eligible: z.boolean(), reason: z.string() }),
  }).passthrough()),
  pricing: z.object({ benchmark_status: z.enum(['sufficient', 'insufficient']), benchmark_message: z.string(),
    comparable_price_count: z.number().int().nonnegative(), minimum_required: z.number().int().positive(),
    currency: z.string(), selling_price: decimal, cost: decimal.nullable(), gross_profit: decimal.nullable(), gross_margin_percent: decimal.nullable(), minimum: decimal.nullable(), median: decimal.nullable(), maximum: decimal.nullable(),
    comparisons: z.array(z.object({ source_id: z.string(), listed_price: decimal, seller_minus_listing: decimal, seller_difference_percent: decimal.nullable() }).passthrough()),
  }).passthrough(),
  report: z.object({ market_overview: finding, competitive_advantages: z.array(finding), competitive_threats: z.array(finding),
    pricing_observations: z.array(finding), recommendations: z.array(finding).length(3),
    classifications: z.array(z.object({ source_id: z.string(), category: z.string(), reason: z.string() })),
  }).passthrough(),
  persistence: z.object({ status: z.enum(['saved', 'disabled', 'error']), report_id: z.string().nullable(), message: z.string(), saved_at: z.string().nullable(), elapsed_ms: z.number().nullable() }).passthrough(),
  caveats: z.array(z.string()),
  evidence_quality: z.object({ sample_size: z.number().int().nonnegative(), band: z.enum(['none', 'single', 'small', 'descriptive']), explanation: z.string(), source_ids: z.array(z.string()) }).nullable().optional(),
  recommendation_safety: z.object({ policy_version: z.string(), status: z.enum(['passed', 'adjusted']), replaced_count: z.number().int().nonnegative(), reason_codes: z.array(z.string()), message: z.string() }).nullable().optional(),
}).passthrough();
export const inspectionSchema = z.object({
  benchmark_available: z.boolean(), benchmark_message: z.string(), comparable_count: z.number(),
  broader_market_note: z.string(), warnings: z.array(z.string()),
  sources: z.array(z.object({ source_id: z.string(), url: z.string(), merchant: z.string().nullable() })),
});
export const briefSchema = inspectionSchema.extend({
  seller_current_price: z.object({ amount: decimal, currency: z.string() }),
  comparable_evidence: z.object({ sample_size: z.number().int(), source_ids: z.array(z.string()), minimum: decimal.nullable(), median: decimal.nullable(), maximum: decimal.nullable() }),
  evidence_confidence: z.string(), suggested_next_steps: z.array(z.string()),
  recommendation_safety_message: z.string(),
  recommendations: z.array(finding).max(3),
  save_status: z.enum(['saved', 'disabled', 'error']), report_id: z.string().nullable(),
  limitations: z.array(z.string()),
});
export type Report = z.infer<typeof reportSchema>;
export type Brief = z.infer<typeof briefSchema>;
export type StepStatus = { id: string; status: 'pending' | 'running' | 'success' | 'failed' | 'skipped'; duration_ms: number | null };
export const stepIds = ['accept-seller', 'fastapi-intelligence', 'inspect-evidence', 'seller-action-brief'];
