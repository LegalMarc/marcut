# Framework Agreement Local LLM Benchmark

Date: 2026-05-12

Test document: `sample-files-marcut/Framework Agreement.docx`

Raw results: `docs/model-benchmarks/framework_agreement_local_llm_benchmark_2026-05-12.json`

## Setup

- Ollama client/server: 0.23.2
- Document size after DOCX paragraph extraction: 52,667 characters, 7,927 words
- Runs: 1 per model
- Ground truth: none for this document, so this is timing and extraction-behavior only. F1/precision/recall are intentionally zero in the raw harness output.
- Timing path: corrected to match the production extraction budget of `num_ctx=12288`, `num_predict=2048`, and `timeout=300`.

## Results

| Model | Installed size | Avg time | Prompt tokens | Output tokens | Entities found |
| --- | ---: | ---: | ---: | ---: | ---: |
| `llama3.2:1b` | 1.3 GB | 6.07s | 10,485 | 66 | 3 |
| `qwen3.5:2b-q4_K_M` | 1.9 GB | 8.93s | 10,617 | 36 | 3 |
| `llama3.2:3b` | 2.0 GB | 13.49s | 10,485 | 49 | 3 |
| `gemma4:e2b` | 7.2 GB | 15.45s | 10,705 | 76 | 3 |
| `phi4-mini:3.8b` | 2.5 GB | 20.59s | 10,403 | 49 | 0 |
| `qwen3.5:9b` | 6.6 GB | 132.59s | 10,617 | 2,048 | 0 |

## Readout

For a smaller-than-Phi fast alternative, `qwen3.5:2b-q4_K_M` is the strongest candidate from this test. It is smaller than `phi4-mini:3.8b`, faster on the Framework Agreement document, and returned the same entity count as the larger `gemma4:e2b` and `llama3.2:3b` runs.

`llama3.2:1b` was fastest, but at 1B parameters it should be treated as a latency floor, not the default recommendation, until we have accuracy evidence on a labeled agreement set.

`gemma4:e2b` does not look like the right fast alternative here. It was 7.2 GB installed and slower than `qwen3.5:2b-q4_K_M`, `llama3.2:1b`, and `llama3.2:3b` on the same document.

`phi4-mini:3.8b` was slower than the 2B Qwen candidate and found no entities in this run. It is not currently the best smaller fallback.

`qwen3.5:9b` is not appropriate for the fast local path on this document. It consumed the full 2,048-token output budget and took 132.59s.

## Recommendation

Offer `qwen3.5:2b-q4_K_M` as the smaller fast local model candidate to test next, with `llama3.2:3b` as the conservative established fallback. Keep `gemma4:e2b` out of the fast path unless a labeled accuracy benchmark shows a material quality gain that justifies its larger footprint and slower runtime.
