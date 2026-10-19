# Milestone 2.1 verification and timing

Measured 2026-10-18 using the live diagnostic script, existing SerpApi configuration and local `gemma3:4b`. Default sample: Milton stainless steel water bottle 1 litre, INR 799 selling price, INR 500 supplied cost, up to five listings per query. No API keys, raw prompts or private provider responses are recorded here.

The completed live analysis returned 10 listings and exactly three source-linked recommendations. Zero listings passed the conservative comparability/price rules; `benchmark_status` was `insufficient`, with null primary minimum/median/maximum. The report retained broader observations separately rather than producing a misleading price benchmark.

| Stage | Wall time | Model loading | Prompt evaluation | Generation |
| --- | ---: | ---: | ---: | ---: |
| Ollama discovery | 1.913 s | 0.008 s | 0.234 s | 1.269 s |
| SerpApi original search | 0.288 s | — | — | — |
| SerpApi broader search | 0.244 s | — | — | — |
| Ollama report | 33.041 s | 0.008 s | 0.362 s | 32.578 s |
| Total server analysis | **35.490 s** | | | |

The standalone caller measured 35.543 s including its own client initialization. Discovery used 136 prompt tokens / 15 generated tokens (11.82 tokens/s). Reporting used 1,083 prompt tokens / 293 generated tokens (8.99 tokens/s). Ollama metadata durations are contained within stage wall time; do not add them again to the total.

Generation consumed about 95% of analysis time. The local model's decoding speed is the remaining bottleneck in this sample; SerpApi and Python processing were small contributors. Model loading was approximately 15 ms combined, so this is a warm/resident-model observation, not a cold-start measurement. Search results may also be cached by the provider; one sample cannot establish uncached search latency or sustained throughput.

An earlier live attempt was safely rejected for an unsupported model price citation. That prompted the generation-schema change: advantages and threats can now cite only the appropriate eligible price IDs, in addition to server-side validation. The final measured run used these constraints. There is no automatic retry or fabricated fallback.

Reproduce (each run may use two SerpApi searches):

```powershell
.\.venv\Scripts\python.exe backend/scripts/benchmark_intelligence.py
```

No streaming, new services, model download, hardware change or new dependencies were introduced. There is no instrumented pre-change baseline, so this measurement does not establish a speedup ratio.
