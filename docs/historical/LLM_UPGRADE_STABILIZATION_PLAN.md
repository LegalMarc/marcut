# LLM Upgrade Stabilization Plan

Generated: 2026-05-12

## Scope

Treat the current dirty worktree as forward project work and stabilize it for commit. The latest edits are centered on local LLM model upgrades, LLM concurrency, model download UX, and related packaging/security adjustments.

## Constraints

- Preserve the PythonKit + BeeWare in-process architecture for the macOS app.
- Keep rules-only mode model-free and deterministic.
- Do not loosen sandbox behavior to make tests easier.
- Keep `qwen2.5:14b` as the normal recommended/default model unless a specific product decision changes that.
- Treat `qwen3.5:35b` as an optional high-resource model, not the default first-run fallback.

## Cleanup Plan

1. Audit dirty LLM/model changes for integration breakage.
2. Wire new options consistently across Python CLI, unified redactor, pipeline, and Swift bridge.
3. Bound and validate `llm_concurrency` before it reaches threaded extraction.
4. Restore deterministic output ordering after parallel chunk extraction.
5. Run Python syntax/unit checks and Swift build/tests where feasible.
6. Stage the cleaned worktree and commit it.

## Initial Findings

- Enhanced mode currently forwards `think_mode` and `format_schema` from `pipeline._collect_enhanced_spans()` without accepting them in the function signature.
- Source CLI lacks `--llm-concurrency`, `--think`, and `--format-schema` arguments while the Swift bridge already passes `--llm-concurrency` in one path.
- First-run setup can fall back to `qwen3.5:35b`, which conflicts with the normal recommended/default `qwen2.5:14b` and may push users toward a model that requires substantially more memory.

## Stabilization Results

- Wired `llm_concurrency`, `think_mode`, and `format_schema` through the Python source CLI, unified redactor, and pipeline.
- Wired `llmConcurrency` through the PythonKit in-process Swift path.
- Bounded threaded LLM extraction concurrency to 1...5 workers.
- Sorted LLM output spans after parallel chunk processing for deterministic downstream merging/reporting.
- Kept `qwen2.5:14b` as the normal default/recommended model and left `qwen3.5:35b` as an optional high-resource model.
- Moved planning/report artifacts under `docs/` and removed scratch Swift probe files.

## Verification

- `PYTHONPATH=src/python python3 -m pytest -q`: 392 passed, 6 skipped.
- `swift test --package-path src/swift/MarcutApp`: 19 passed.
- `python3 -m py_compile src/python/marcut/chunker.py src/python/marcut/model_enhanced.py src/python/marcut/pipeline.py src/python/marcut/unified_redactor.py src/python/marcut/cli.py`: passed.
- `git diff --check`: passed.
