# Design Spike: WebAssembly / Browser Deployment via Pyodide

Status: Design spike (no code changes). Companion to issue #29.

## Goal

`backlog.md`'s "Major New Directions" section lists: *"WebAssembly /
Browser Deployment: Compile the deterministic Python rule engine to WASM
using Pyodide to create a fully in-browser, zero-install offline redaction
fallback."* This doc evaluates whether that is worth pursuing, covering
technical feasibility, the rules-only accuracy limitation relative to this
project's own stated requirements, a threat-model comparison against the
current local-first native app, and a recommendation.

**This ticket does not implement anything.** Per the ticket Notes, a
recommendation against pursuing this, with clear reasoning, is a fully
acceptable outcome.

## 1. Feasibility / Rules-Only Limitation

### What could plausibly run under Pyodide

The rules engine (`src/python/marcut/rules.py`, ~1,065 lines) is
deterministic, pure-Python pattern matching over the extracted document
text: regex-based detection of emails, phone numbers, credit cards, dates,
money amounts, account numbers, and excluded-term filtering, backed by an
in-process cache (`_exclusion_data_cache`) loaded from `excluded-words.txt`.
It has one third-party dependency, `regex` (a drop-in `re` replacement),
which is pure C but ships prebuilt wheels; Pyodide's package index
carries it, so this module is a realistic Pyodide candidate on its own.

The pipeline already has a rules-only code path in production:
`run_redaction()` in `src/python/marcut/pipeline.py` dispatches on `mode`,
and `rules_only_modes = {"rules", "strict", "rules_only"}` (pipeline.py:1692)
skips the LLM entirely — `_collect_rule_spans()`, boundary snapping,
organization-suffix extension, defined-term alias attachment, and the
rules-only consistency pass all run without Ollama. This is the existing,
already-shipped analog of what a WASM build would offer: a redaction path
whose accuracy ceiling is "whatever pattern matching alone can find."

### What explicitly cannot run this way

Two things anchor why a WASM build could not be the LLM-based pipeline,
only a fallback of it:

- **The Ollama-based LLM engine cannot run in-browser as designed.**
  `model.py` and `model_enhanced.py` call the Ollama HTTP API
  (`http://localhost:11434`) via `requests`. Ollama is a native binary
  managed by `ollama_manager.py`/`bootstrapper.py` — it is not a Python
  module and has no WASM target. A browser sandbox cannot spawn or
  supervise a local subprocess, and CLAUDE.md's own project overview
  states the current architecture depends on "an embedded Ollama binary
  for self-contained AI processing." There is no plausible way to carry
  that into a browser tab; it would have to be dropped entirely, not
  ported.
- **CLAUDE.md is explicit that LLM detection is required for legal
  documents**: *"LLM detection is required for legal documents — rules
  alone miss names and organizations."* This is not an implementation
  detail, it is a stated accuracy floor for the product. A Pyodide build
  of the rules engine, by construction, would be exactly the
  "rules alone" case CLAUDE.md warns against. **A WASM build would
  therefore be rules-only, and per the project's own documented accuracy
  requirement, not suitable for legal documents unless that requirement
  is separately revisited as a product decision** — this is not something
  a build-tooling change can resolve.

### Secondary feasibility obstacles, even for the rules-only slice

Even bounding scope to "rules engine only," the rest of the pipeline the
rules engine feeds into is not obviously portable:

- **DOCX I/O depends on native extensions.** `docx_io.py` (2,413 lines)
  uses `python-docx`, which depends on `lxml`, a C-extension library
  (`libxml2`/`libxslt` bindings). `lxml` is on Pyodide's package index but
  is a large, non-trivial WASM build with periodic version lag behind
  PyPI; `pyproject.toml` currently pins `lxml>=6.1.0`, and there is no
  guarantee the Pyodide-packaged version tracks that. A browser fallback
  would need either a compatible Pyodide `lxml` build or a rewrite of the
  DOCX-writing path onto a pure-JS/WASM ZIP+XML library, which is a
  materially different, larger effort than "compile the rules engine."
- **Track-changes generation is intricate OOXML manipulation.** The
  revision-element writer this produces (`OxmlElement`/`qn()`-based
  insertion/deletion markup) is exactly the kind of code most likely to
  behave subtly differently under a different lxml build or version —
  and subtle DOCX corruption is a much worse failure mode for a redaction
  tool than a crash, per `docs/SECURITY.md`'s "Redaction Failures:
  Scenarios where 'redacted' text is recoverable from the DOCX structure"
  threat category.
- **Pyodide's startup cost is real.** A full Pyodide runtime plus `lxml`
  and `numpy` (a `pyproject.toml` dependency, also present for
  `dateparser`/`rapidfuzz` transitively) is commonly tens of megabytes to
  fetch and multiple seconds to initialize on first load — workable for
  an occasional-use fallback tool, but worth naming as a UX cost rather
  than assuming "zero-install" implies "instant."

### Summary

The rules engine itself is a plausible Pyodide candidate in isolation. The
DOCX-writing path it must feed into is a materially larger and riskier
port. And most importantly, whatever ships would be bounded by the
rules-only accuracy ceiling that CLAUDE.md already documents as
insufficient for this product's stated use case (legal documents).

## 2. Threat-Model Comparison

`docs/SECURITY.md` frames the current app's security posture around three
properties that a browser deployment would each change:

| Property (current native app) | Native app today | Browser/Pyodide build |
|---|---|---|
| **Network isolation** | "Marcut processes all documents locally. Network access is restricted to `localhost` (Ollama) and explicit model downloads. No telemetry or usage data is collected." | The redaction *computation* could stay client-side (Pyodide runs in-page), but the user must first load the page itself from a server over the network, every time, unless it is deliberately shipped as an offline-capable PWA with a service worker and an explicit "you may now disconnect" affordance. Absent that, "zero-install offline" is aspirational, not automatic. |
| **Trust boundary / execution sandbox** | Code-signed, notarized native macOS binary running as a normal user process; Apple's notarization pipeline and Gatekeeper are the integrity check between "what was published" and "what is running." | Runs inside the browser's JS/WASM sandbox — a different and in some ways stronger sandbox (no filesystem access outside what the page explicitly requests), but the integrity guarantee shifts from code-signing to "did you load the page from the right origin over an uncompromised connection." There is no macOS notarization equivalent for a web page; a compromised CDN, a MITM'd connection on first load, or a malicious/typosquatted mirror of the page can silently swap in a modified WASM bundle, and the user has no OS-level signal (Gatekeeper prompt, signature mismatch) to detect it the way they would with a tampered `.app`. |
| **Document handling / data egress** | Documents are read from and written to local disk via the sandboxed macOS file-access model (`docs/SECURITY.md`'s "Sandbox Escapes: Arbitrary file access outside the sandboxed Application Support container" threat category); zip/XML parsing hardened against XXE and zip-slip. | Documents would be handled via browser File API (drag-drop or file picker) — access is user-gesture-scoped and arguably *more* restrictive than a native app's filesystem access, which is a genuine advantage. But the page hosting the WASM bundle sits between the user and that guarantee: if the page itself (not just the WASM module) is compromised, malicious JS on the same origin can read the File API contents before they ever reach the Pyodide sandbox — a failure mode with no analog in a native app, where the redaction binary is the only thing with access to the file. |
| **Update integrity / supply chain** | DMG is code-signed and notarized (`scripts/notarize_macos.sh`, `scripts/sh/build_devid_release.sh`); users get a specific, verifiable build. | Web deployments typically auto-update on every page load, which is good for patching but bad for auditability — there is no persistent, user-visible "version N is what I'm running and what I chose to trust" the way a locally-installed, signed app provides. A subtly backdoored WASM bundle pushed to the CDN would reach every user on their next page load with no signature check equivalent to Gatekeeper. |
| **Dependency vulnerability surface** | Tracked via `scripts/check_dependency_vulnerabilities.py` and `docs/release/python-sbom.json` against a fixed, versioned, code-signed dependency set. | Pyodide bundles its own build of CPython plus every WASM-compiled dependency; those builds are on their own release cadence, separate from the PyPI packages `pyproject.toml` pins, meaning a new class of "SBOM says X, Pyodide is actually shipping Y" drift to track. |

**Net assessment:** the browser sandbox is not strictly worse than the
native app's — File API scoping and no ambient filesystem access are real
advantages — but it trades a code-signing/notarization-based trust model
(verify once, at install, via the OS) for a load-time trust model (verify
implicitly, on every page load, via TLS and hoping the origin wasn't
compromised). For a tool whose stated purpose is handling "sensitive legal
and personal documents" (`docs/SECURITY.md`), that is a meaningfully
different — not obviously better — risk profile, and it is a new class of
threat this project's current threat model and security tooling (SBOM
generation, dependency-vulnerability scanning, notarization) are not built
to cover.

## 3. Recommendation

**Do not pursue this now.** Two independent blockers, either one of which
is sufficient on its own:

1. **Accuracy**: any WASM build is rules-only by construction (the LLM
   engine cannot run in-browser as architected), and CLAUDE.md already
   states rules-only detection is not sufficient for this product's core
   use case — legal documents. Shipping a rules-only fallback under the
   Marcut name risks a lawyer treating "ran in the browser" as
   equivalent to "ran the real pipeline," when it structurally cannot
   catch what the LLM pass catches. If this is pursued, the accuracy gap
   would need to be surfaced so prominently in the UI (not a caveat in
   documentation) that it is closer to a distinct, differently-branded
   "quick scan" tool than a deployment option for the same product.
2. **Threat model**: this project's security posture, tooling (SBOM,
   dependency scanning, notarization), and documentation are all built
   around the local-first, code-signed native app model. A browser
   deployment introduces load-time trust and page-compromise risks that
   nothing in the current security program addresses, for a category of
   documents (legal, personal PII) where that gap matters more than for
   most software.

**What would need to change first**, if this is revisited later:

- A product decision to explicitly relax or reframe the "LLM required for
  legal documents" stance for a clearly-labeled fallback tier — not an
  engineering decision, a decision about what Marcut is allowed to claim
  about its own output.
- A concrete plan for load-time integrity (subresource integrity hashes,
  a signed/pinned deployment origin, and/or a PWA/service-worker model
  that lets a user "install" a specific verified version rather than
  trusting every page load fresh) that gives the browser deployment
  something resembling the native app's notarization guarantee.
- Validation that `lxml` (or a replacement DOCX-writing path) is
  reliably buildable and version-tracked under Pyodide, since the
  track-changes writer is the component most sensitive to subtle
  behavioral drift and the one with the worst failure mode
  (silently-wrong redaction output) if it isn't.

Absent those three, the rules-only limitation and the threat-model delta
both point the same direction: this is worth revisiting only if the
product's accuracy and trust requirements for a browser tier are
explicitly redefined, not something to greenlight as a build-tooling
exercise on the current requirements.
