# Performance Optimization Guide

This document captures performance profiling data and optimization recommendations for Marcut's LLM-based redaction pipeline.

## Quick Summary

**Bottom Line**: For LLM-enhanced redaction, **token generation is 81% of processing time**. Optimizations should focus on reducing output tokens and using faster models, rather than caching or parallelization alone.

---

## Profiling Tools

Marcut includes built-in timing instrumentation accessible via CLI flags:

### Basic Phase Timing
```bash
marcut redact --in doc.docx --out out.docx --report report.json --timing
```

Shows time spent in each processing phase:
- `DOCX_LOAD` - Document loading and revision acceptance
- `RULES` - Rule-based entity detection
- `LLM` - AI model inference (enhanced mode only)
- `POST_PROCESS` - Boundary snapping, consistency pass, merge
- `DOCX_SAVE` - Track changes, hardening, file write

### Detailed LLM Timing
```bash
marcut redact --in doc.docx --out out.docx --report report.json --llm-detail
```

Breaks down the LLM phase into sub-components:
- `ollama_model_load` - Time loading model into GPU memory
- `ollama_prompt_eval` - Processing input tokens
- `ollama_generation` - Generating output tokens
- `network_overhead` - HTTP latency minus Ollama processing
- `response_parse` - JSON parsing of LLM response
- `entity_locate` - Finding entity positions in document text

---

## Profiling Results

### Test Configuration
- **Model**: llama3.1:8b (Q4_K_M quantization)
- **Document**: Shareholder-Consent.docx (sample legal document)
- **Hardware**: Apple Silicon Mac
- **Mode**: Enhanced (rules + LLM)

### Phase-Level Breakdown

| Phase | Time | Percentage |
|-------|------|------------|
| DOCX_LOAD | 0.004s | 0.4% |
| RULES | 0.000s | <0.1% |
| **LLM** | **1.091s** | **97.9%** |
| POST_PROCESS | 0.000s | <0.1% |
| DOCX_SAVE | 0.019s | 1.7% |

**Key Finding**: LLM processing dominates at ~98% of total time.

### LLM Sub-Phase Breakdown

| Sub-Phase | Time | Percentage | Notes |
|-----------|------|------------|-------|
| ollama_model_load | 0.059s | 5.4% | Model was warm (already in GPU) |
| ollama_prompt_eval | 0.116s | 10.6% | Processing 458 input tokens |
| **ollama_generation** | **0.883s** | **81.1%** | Generating 56 output tokens |
| network_overhead | 0.007s | 0.6% | HTTP latency |
| response_parse | 0.000s | <0.1% | JSON parsing |
| entity_locate | 0.001s | 0.1% | Finding spans in text |

**Key Finding**: Token generation (81%) is the dominant factor, not model loading or prompt processing.

### Cold Start vs Warm Model

When the model is **not** already loaded in GPU memory:

| Metric | Cold Start | Warm |
|--------|-----------|------|
| Model Load | ~3.0s | ~0.06s |
| Total LLM | ~4.5s | ~1.1s |

First-run latency is 4x higher due to model loading.

---

## Token Statistics

For the test document:
- **Input tokens**: 458 (prompt + document text)
- **Output tokens**: 56 (entity JSON response)
- **Generation speed**: ~63 tokens/sec on Apple Silicon

---

## Optimization Recommendations

Based on profiling data, prioritized by expected impact:

### Tier 1: High Impact, Low Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Shorter prompts** | 10-15% | Low - Reduce system prompt size |
| **Lower `num_predict`** | 5-20% | Low - Cap max output tokens |
| **Smaller model** (3B vs 8B) | 50-70% | Low - Config change |

### Tier 2: Medium Impact, Low Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Cache/dedupe decisions** | 5-20x (repetitive docs) | Medium |
| **Parallelize chunks** | 2-4x (multi-core) | Medium |

### Tier 3: Medium Impact, Medium Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Quantized model** (Q4 vs Q8) | 20-40% | Low - Model swap |
| **Two-pass triage** | Variable | High - Threshold tuning |

---

## Implementation Notes

### Prompt Optimization

Current prompt is ~400 tokens. Potential reductions:
- Remove verbose entity type descriptions
- Use few-shot examples efficiently
- Consider instruction-tuned models that need less prompting

### Output Token Limits

Current `num_predict: 512` is generous. Consider:
- Reducing to 256 for typical documents
- Implementing streaming to detect early completion

### Model Selection Trade-offs

| Model | Speed | Accuracy | Size |
|-------|-------|----------|------|
| llama3.2:1b | Fastest | Acceptable | 1.3GB |
| llama3.2:3b | Fast | Good | 2.0GB |
| llama3.1:8b | Moderate | Best | 4.9GB |

For most legal documents, 3B provides good accuracy/speed balance.

### Caching Strategy

Hash key should include:
- Normalized text (stripped whitespace)
- Model identifier
- Prompt version hash

Invalidation: Clear cache when model or prompt changes.

---

## Monitoring

For ongoing performance monitoring:

```python
# Enable timing in Python code
from marcut.pipeline import run_redaction

exit_code, timings = run_redaction(
    input_path="doc.docx",
    output_path="out.docx",
    report_path="report.json",
    mode="enhanced",
    model_id="llama3.1:8b",
    timing=True,
    llm_detail=True,
    # ... other params
)

# Access timing data
print(f"LLM time: {timings['LLM']:.2f}s")
if 'llm_timing' in timings:
    print(f"Generation: {timings['llm_timing']['ollama_generation']:.2f}s")
```

---

## Related Files

- [`marcut/llm_timing.py`](../marcut/llm_timing.py) - LLM timing instrumentation
- [`marcut/cli.py`](../marcut/cli.py) - CLI flag handling
- [`marcut/pipeline.py`](../marcut/pipeline.py) - Main processing pipeline
- [`marcut/model.py`](../marcut/model.py) - Ollama integration

---

*Last updated: December 2024*
