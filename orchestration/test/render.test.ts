import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import GuidedAnalysis from '../../frontend/src/components/GuidedAnalysis.tsx';
import IntelligenceReportView from '../../frontend/src/components/IntelligenceReportView.tsx';
import IntelligencePanel from '../../frontend/src/components/IntelligencePanel.tsx';
import type { GuidedRun } from '../../frontend/src/guided.ts';
import type { Intelligence } from '../../frontend/src/api.ts';
import { buildBrief, inspectReport } from '../src/workflow.js';
import { reportSchema } from '../src/contracts.js';
import { reportFixture } from './fixture.js';

test('guided output and existing report render with evidence, save status and opt-in prediction', () => {
  const report = reportSchema.parse(reportFixture());
  const run = { run_id: 'test-run', status: 'success', duration_ms: 30, steps: [], result: { report, action_brief: buildBrief(report, inspectReport(report)) } } as unknown as GuidedRun;
  const guided = renderToStaticMarkup(createElement(GuidedAnalysis, { run }));
  assert.match(guided, /Seller action brief/); assert.match(guided, /Insufficient comparable evidence/);
  assert.match(guided, /Report saving: disabled/); assert.match(guided, /https:\/\/shop.example\/item/);
  assert.match(guided, /What the data shows/); assert.match(guided, /What the seller could do/); assert.match(guided, /What remains uncertain/);
  assert.match(guided, /Your current price: INR 150/); assert.match(guided, /individual observation/);
  const original = renderToStaticMarkup(createElement(IntelligenceReportView, { data: report as unknown as Intelligence }));
  assert.match(original, /Insufficient comparable products/); assert.match(original, /experimental|Experimental/);
  const form = renderToStaticMarkup(createElement(IntelligencePanel));
  assert.match(form, /Generate intelligence report/); assert.match(form, /Run guided analysis/);
});
