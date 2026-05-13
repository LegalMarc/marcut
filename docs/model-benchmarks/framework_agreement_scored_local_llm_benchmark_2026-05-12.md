# Framework Agreement Scored Local LLM Benchmark

Date: 2026-05-12

Test document: `sample-files-marcut/Framework Agreement.docx`

Ground truth: `docs/model-benchmarks/framework_agreement_ground_truth_2026-05-12.json`

Raw scored results: `docs/model-benchmarks/framework_agreement_scored_local_llm_benchmark_2026-05-12.json`

## Ground Truth

The ground truth contains one canonical occurrence per distinct extractable entity text, matching the benchmark scorer's fuzzy `(text, label)` comparison:

| Text | Label |
| --- | --- |
| `Plant-A Insights Group LLC` | ORG |
| `TIME USA, LLC` | ORG |
| `Plant-A Insights LLC` | ORG |
| `A.M. Best` | ORG |
| `Delaware` | LOC |
| `United States` | LOC |
| `New York` | LOC |
| `Kings County` | LOC |

Aliases and repeated shorthand references such as `Plant-A`, `Publisher`, and `TIME` were not included because the current extraction prompt and validation rules target company names, people, and locations, and reject many one-token aliases.

## Scored Results

| Rank | Model | Installed size | Avg time | Precision | Recall | F1 | Entities found | Readout |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `llama3.2:1b` | 1.3 GB | 4.93s | 1.00 | 0.25 | 0.40 | 3 | Fastest model with tied-best F1. |
| 2 | `qwen3.5:2b-q4_K_M` | 1.9 GB | 7.07s | 1.00 | 0.25 | 0.40 | 3 | Best smaller-than-Phi candidate. |
| 3 | `gemma4:e2b` | 7.2 GB | 9.97s | 1.00 | 0.25 | 0.40 | 3 | Same accuracy as Qwen 2B, but larger and slower. |
| 4 | `llama3.2:3b` | 2.0 GB | 10.94s | 1.00 | 0.25 | 0.40 | 3 | Same score as Qwen 2B, slower. |
| 5 | `phi4-mini:3.8b` | 2.5 GB | 12.17s | 0.00 | 0.00 | 0.00 | 0 | No matching entities found. |
| 6 | `qwen3.5:9b` | 6.6 GB | 95.07s | 0.00 | 0.00 | 0.00 | 0 | Too slow and no matching entities in this run. |

## Recommendation

For the fast local option, prefer `qwen3.5:2b-q4_K_M` over `phi4-mini:3.8b` and `gemma4:e2b`. It tied the best observed F1 on this agreement, was materially faster than Gemma E2B, and is smaller than Phi Mini.

`llama3.2:1b` is the pure latency winner, but because it is a 1B model, it should be treated as an ultra-fast mode rather than the default fast model until a larger labeled document set confirms that it does not collapse on harder documents.

The low recall across the tied models suggests the bottleneck is at least partly prompt/extraction strategy, not just model selection. The next improvement should be chunking or a contract-aware prompt that separately asks for parties, defined organizations, rating agencies, and governing-law locations.
