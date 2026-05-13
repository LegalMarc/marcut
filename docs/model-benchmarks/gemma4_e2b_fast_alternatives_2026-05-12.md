# Gemma4 E2B Fast Alternatives Benchmark

Date: 2026-05-12

## Scope

Quick one-pass screening benchmark for `gemma4:e2b` and smaller local alternatives to `phi4-mini:3.8b`.

This is not a product-decision-grade evaluation. It uses one short preservation-letter sample with 4 manually verified expected entities. Treat the result as a fast signal for which models deserve broader legal-document testing.

Raw results: `docs/model-benchmarks/gemma4_e2b_fast_alternatives_2026-05-12.json`

## Environment Changes

- Upgraded system Ollama from `0.19.0` to `0.23.2` because `gemma4:e2b` requires a newer Ollama.
- Downloaded:
  - `gemma4:e2b`
  - `phi4-mini:3.8b`
  - `qwen3.5:2b-q4_K_M`

## Results

| Model | Size Class | Avg Time | Precision | Recall | F1 | Entities Found |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `llama3.2:3b` | 2.0 GB | 2.55s | 0.67 | 0.50 | 0.57 | 3 |
| `qwen3.5:9b` | 6.6 GB | 10.16s | 0.30 | 0.75 | 0.43 | 10 |
| `phi4-mini:3.8b` | 2.5 GB | 23.27s | 0.33 | 0.25 | 0.29 | 3 |
| `llama3.2:1b` | 1.3 GB | 1.95s | 0.33 | 0.25 | 0.29 | 3 |
| `qwen3.5:2b-q4_K_M` | 1.9 GB | 13.30s | 0.25 | 0.25 | 0.25 | 6 |
| `gemma4:e2b` | 7.2 GB | 5.62s | 0.17 | 0.25 | 0.20 | 8 |
| `qwen3.5:4b` | 3.4 GB | 12.24s | 0.08 | 0.25 | 0.12 | 14 |

## Preliminary Read

`llama3.2:3b` is the best smaller-than-Phi candidate from this quick screen. It is smaller than `phi4-mini:3.8b`, much faster on this sample, and had materially better F1.

`qwen3.5:2b-q4_K_M` is also smaller than Phi, but this first run does not justify promoting it.

`gemma4:e2b` should not replace the fast slot based on this run alone. It is modern and fast enough, but it over-redacted this sample and is much larger than Phi.

## Recommended Next Step

Run the full legal-document matrix before changing the supported model list:

- Include multiple representative DOCX samples, not just the preservation letter.
- Score missed redactions and unnecessary redactions separately.
- Compare `llama3.2:3b`, `phi4-mini:3.8b`, `gemma4:e2b`, `qwen3.5:2b-q4_K_M`, and the current recommended model.
- Re-test with the app's constrained override mode, not only raw extraction.
