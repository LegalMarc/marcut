# Design Spike: Local RAG / Cross-Document Entity Graph for Consistent Redaction

Status: Design spike (no code changes). Companion to issue #28.

## Goal

Today every `run_redaction()` / `run_redaction_enhanced()` call
(`src/python/marcut/pipeline.py`) is a closed world: entity clustering,
sequential ID assignment, and confidence scoring all happen inside a single
`ClusterTable` instance that is constructed fresh in `_finalize_and_write()`
(`pipeline.py:1298`) and discarded when the function returns. If a user
redacts "John Doe" as `[NAME_3]` in `Document-A.docx` and then separately
redacts `Document-B.docx`, which refers to the same person as "Mr. Doe," the
pipeline has no memory of the first document and no way to connect the two
mentions. Per `backlog.md`'s "Major New Directions" section: *"Local RAG
across Document Sets: Implement a local Vector DB to store client references
cross-document. If 'John Doe' is redacted in Doc A, automatically pre-redact
'Mr. Doe' in Doc B using graph clustering."*

This doc proposes how a cross-document entity index could reuse the existing
single-document clustering mechanism, what a fully local storage layer for it
would look like, and — because this is the first feature in the codebase
that would deliberately persist entity information *across* otherwise
independent documents — a privacy/confidentiality analysis of what that
means for a tool whose entire value proposition today is that it does not
retain anything.

**This ticket does not implement the feature.** It exists because the
retention-model change described below is a product and privacy decision
that needs explicit human sign-off before any code is written, not merely an
engineering task to be scoped and built.

## Relationship to the existing `ClusterTable`

The existing single-document mechanism (`src/python/marcut/cluster.py`) is
small and worth restating in full, because the cross-document proposal is
best understood as "the same algorithm, given a longer-lived and
differently-scoped backing store" rather than a new system:

```python
class ClusterTable:
    def __init__(self):
        self.next_name = 1; self.next_org = 1; self.next_brand = 1
        self.clusters: Dict[str, List[Dict[str,Any]]] = {"NAME":[], "ORG":[], "BRAND":[]}

    def link(self, label: str, surface: str) -> Tuple[str, float, bool]:
        n = normalize(surface)
        best = (None, 0.0)
        for cl in self.clusters[label]:
            for alias in cl["aliases"]:
                s = fuzz.token_set_ratio(n, alias) / 100.0
                if s > best[1]: best = (cl, s)
        if best[0] and (best[1] >= 0.82 or n in best[0]["aliases"]):
            best[0]["aliases"].add(n)
            return best[0]["id"], best[1], False
        cid = self._new_id(label)
        self.clusters[label].append({"id": cid, "aliases": {n}, "canonical": n})
        return cid, 1.0, True
```

Three properties of this design carry over directly and constrain the
cross-document proposal:

1. **Scope is entirely in `label` (`NAME`/`ORG`/`BRAND`) and `surface`
   text.** There is no positional, structural, or document-identity
   information in a cluster — a cluster is just a label plus a growing set of
   normalized alias strings plus a stable ID. This is *good* for a
   cross-document extension: the matching primitive (`normalize()` +
   `fuzz.token_set_ratio`) is document-agnostic already, so nothing about the
   matching algorithm itself needs to change to span documents. What needs
   to change is only *what constructs the `ClusterTable` and how long it
   lives*.

2. **`normalize()` (`cluster.py:7-14`) is deliberately lossy** — it
   lowercases, strips legal suffixes (`inc`, `llc`, `corp`, ...), strips
   punctuation, and collapses whitespace. That is calibrated for
   within-document noise (e.g., "Acme Corp." vs. "Acme Corporation" in the
   same contract). Cross-document matching raises the stakes on this same
   normalization: a looser threshold that's harmless when both mentions are
   two paragraphs apart in one contract becomes a cross-*client*
   false-positive risk when the two mentions are in unrelated matters filed
   months apart (see "Cross-matter collision risk" below). The 0.82
   `token_set_ratio` threshold and the "alias-only" exact-match fallback
   (`n in best[0]["aliases"]`) were tuned for single-document recall, not for
   safety against merging two different people who happen to share a
   surname across matters.

3. **IDs are sequential and per-run** (`next_name`, `next_org`,
   `next_brand`, reset to 1 in `__init__`). `[NAME_3]` in one document's
   output has no relationship to `[NAME_3]` in another document's output
   today — they are coincidentally identical labels for what could be two
   different people. A cross-document graph needs a durable identity per
   real-world entity (a UUID or content-derived key) that is stable across
   runs, with the human-facing `[NAME_n]` numbering *derived* from that
   durable identity per-document at redaction time, the same way it's
   derived from the in-memory `ClusterTable` today. This is the one place
   where "reuse" means "reuse the concept, not the field" — `next_name`
   as a simple incrementing counter cannot be the durable key because two
   concurrent documents redacted in parallel would race on it, and because
   the whole point is for the number to be *stable* across documents that
   may be processed weeks apart.

### Proposed integration point

`_finalize_and_write()` constructs `ct = ClusterTable()` and calls
`ct.link(label, text)` per span (`pipeline.py:1298-1316`). The proposed
cross-document layer sits **behind** that call, not instead of it:

- `ClusterTable` gains an optional constructor argument, e.g.
  `ClusterTable(seed_aliases: Optional[Dict[str, List[Dict]]] = None)`,
  pre-populated by a new lookup against the cross-document store, scoped to
  the current matter (see below). This means a document's *first* pass
  still only ever sees the reduced, pre-filtered alias set the store hands
  it — not the raw store — so the existing O(clusters × aliases) linear scan
  in `link()` stays bounded by what's relevant to this matter, not by the
  store's total size.
- After redaction, the same `ct.clusters` structure (label → canonical →
  aliases → id) is the natural write-back unit: for each cluster, upsert one
  row keyed by durable entity ID, with the new document's aliases merged in.
  This reuses the exact grouping the pipeline already computes for the
  Track-Changes output; no separate extraction pass is needed to build the
  cross-document index.
- The rest of `_finalize_and_write()` — sequential per-document
  `[LABEL_n]` numbering, `entity_counters` for non-NAME/ORG/BRAND types,
  replacement construction — is unaffected. Only `ClusterTable` construction
  and a post-pass write-back change.

This keeps the blast radius of an eventual implementation small and
reviewable: the diff is "seed and persist a `ClusterTable`," not "redesign
entity clustering."

## Local storage proposal

The app is explicitly local-first with no external API calls
(`CLAUDE.md`: *"All processing is local-first with no external API calls"*;
`docs/SECURITY.md`: *"Marcut processes all documents locally. Network access
is restricted to localhost (Ollama) and explicit model downloads."*). Any
storage choice here must not introduce a network dependency, a server
process, or a cloud SDK — the "vector DB" framing in `backlog.md` should be
read as "similarity index," not as a mandate for a specific technology.

### What actually needs to be stored

The matching primitive that already exists (`fuzz.token_set_ratio` over
normalized strings) is a **lexical/fuzzy string index**, not a semantic
embedding index. "John Doe" → "Mr. Doe" is exactly the kind of alias
relationship `ClusterTable.link()` already resolves via
`token_set_ratio` — no embedding model is required to catch it. A true
vector/embedding store would additionally catch *semantic* aliasing with no
lexical overlap (e.g., "the Acquirer" → "Northwind Capital LLC" from
context), which is a materially different and harder problem: it requires
an embedding model running locally (another Ollama model pull, more disk,
more inference time per document) and a similarity index (e.g., HNSW) on
top, for a class of match the current pipeline's LLM-based extraction
(`model_enhanced.py`) already partially handles via document-level context
within a single document, but does not currently attempt across documents.

**Recommendation: start with the fuzzy-lexical index, not a vector/embedding
index**, for three reasons:
- It's a direct extension of `ClusterTable`, which is already validated in
  production for the single-document case — same algorithm, longer-lived
  store.
- It has zero new inference cost: no embedding model to download, load, or
  run per document, which matters for an app whose "0.41s end-to-end" and
  "10s per phase" timeout budget (`CLAUDE.md`'s PythonKit init section) is
  already tight.
- It's auditable in a way embeddings are not: a support/debugging session
  can inspect the alias list for a cluster and see in plain text why two
  mentions were linked, which matters for a legal tool where a human may
  need to justify why a redaction did or didn't happen (see
  `docs/SECURITY.md`'s existing emphasis on auditability of redaction
  decisions). A future semantic layer could be added later as an *additional
  candidate generator* feeding the same `link()` decision, without changing
  the storage or privacy model described here.

### Candidate storage mechanism

Given a fuzzy-lexical index, the storage need is small: for each
`(matter_id, label)`, a list of clusters, each `{id, canonical, aliases:
set[str], source_documents: list[{path_hash, redacted_at}]}`. This is
well within SQLite's comfort zone and does not need a dedicated
vector-DB dependency:

- **SQLite**, via the stdlib `sqlite3` module (no new dependency at all),
  with a schema like:
  ```sql
  CREATE TABLE matters (
      matter_id TEXT PRIMARY KEY,
      display_name TEXT,
      created_at TEXT
  );
  CREATE TABLE entity_clusters (
      cluster_id TEXT PRIMARY KEY,
      matter_id TEXT NOT NULL REFERENCES matters(matter_id),
      label TEXT NOT NULL CHECK (label IN ('NAME','ORG','BRAND')),
      canonical TEXT NOT NULL,
      created_at TEXT NOT NULL
  );
  CREATE TABLE entity_aliases (
      cluster_id TEXT NOT NULL REFERENCES entity_clusters(cluster_id),
      alias_normalized TEXT NOT NULL,
      PRIMARY KEY (cluster_id, alias_normalized)
  );
  CREATE TABLE entity_source_documents (
      cluster_id TEXT NOT NULL REFERENCES entity_clusters(cluster_id),
      document_path_hash TEXT NOT NULL,  -- SHA-256 of the resolved path, not the path itself
      redacted_at TEXT NOT NULL
  );
  CREATE INDEX idx_aliases_matter_label
      ON entity_aliases(alias_normalized);
  ```
  One `.marcut/matters.db` file (or one file per matter — see below) with
  WAL mode for crash-safety, indexed on `alias_normalized` for the seed
  lookup. This puts candidate generation for a new document at "index
  lookup on normalized substrings/tokens, then `token_set_ratio` re-rank on
  the shortlist" — the same two-stage shape as the in-memory version, just
  with the first stage backed by a persistent index instead of a Python
  list.
- **Why not a dedicated embedding vector DB (Chroma, LanceDB, sqlite-vec,
  etc.) for the MVP**: none are currently a dependency (`pyproject.toml` has
  no vector-store package), each adds install size and a new native
  extension to code-sign for the App Store build (the project's BeeWare
  packaging pipeline already treats "every `.so`/`.dylib` needs deep
  signing" as a first-class build concern per `CLAUDE.md`'s BeeWare
  section), and none are needed unless/until the semantic-matching
  extension above is actually pursued. If that extension is pursued later,
  `sqlite-vec` (a SQLite extension, not a separate service) would be the
  natural choice specifically because it preserves the "one local file,
  one dependency-light engine" property this proposal is optimizing for —
  a standalone server-based vector DB (e.g., a self-hosted Chroma server)
  would reintroduce a network dependency this app has specifically avoided.

## Privacy/confidentiality analysis

This is the section that most needs human sign-off, because it is a change
in kind, not degree, from the app's current data-handling posture.

### The retention-model change

Today, per `docs/SECURITY.md`, the security promise is per-document and
zero-retention: input DOCX in, redacted DOCX + JSON audit report out,
nothing about *this document's* content persisted anywhere afterward beyond
what the user explicitly saves. `ClusterTable` is constructed and discarded
within a single `_finalize_and_write()` call; nothing about "John Doe" from
Document A exists in memory or on disk once that call returns.

Cross-document matching is only possible by definition if *something* about
Document A's entities outlives Document A's redaction — a name, a
normalized alias, and enough of a fingerprint to match it against Document
B later. That is a new, standing, on-disk record of who appeared in a
user's previously-redacted documents, indexed by name. For a tool whose
users are handling legally privileged and confidential material, this is
the single highest-stakes design decision in this proposal, independent of
which storage engine backs it.

### Cross-matter/cross-client data isolation

The core risk is concrete: a solo practitioner or small firm using Marcut
across multiple clients must never have Client A's entity index leak into,
or be visible during, Client B's redaction — both because it would be a
confidentiality breach in itself (the mere existence of a cross-reference
between two clients' matters can itself be privileged information, e.g. in
conflict-of-interest-sensitive practices) and because an incorrect
cross-matter match (see below) could actively corrupt Client B's redaction
output.

Proposed isolation model:

- **Every cluster and alias is scoped to a `matter_id`**, per the schema
  above. There is no global cross-matter index by default — `link()`'s
  candidate lookup must filter on `matter_id` as a hard precondition, not an
  optional ranking signal, mirroring how `ClusterTable.clusters` is already
  strictly partitioned by `label` today (a `NAME` cluster is never a
  candidate match for an `ORG` span, by construction, and the code has no
  path that would let it be — matter isolation should have the same
  structural guarantee, not a filter that a future refactor could
  accidentally loosen).
- **Matter boundaries must be explicit user action, not inferred.** The
  pipeline has no notion of "matter" today (`grep` across `CLAUDE.md`,
  `docs/SECURITY.md`, and `backlog.md` turns up zero prior references to
  "matter" or "client" as a data concept) — this would be new UI and a new
  concept the user actively manages: create a matter, assign documents to
  it, and the cross-document index only ever looks within that matter's own
  cluster set. Auto-inferring matter membership from document content or
  filename would risk silently merging two clients' data based on a wrong
  guess, which is a worse failure mode than requiring explicit setup.
- **Per-matter storage should be independently deletable.** Splitting the
  proposed SQLite schema into one physical file per matter (e.g.
  `~/.marcut/matters/<matter_id>.db`), rather than one shared database
  partitioned by a `matter_id` column, makes "delete Client A's entity
  history when the engagement ends" a single `rm`, verifiable by a user or
  auditor without needing to trust a `DELETE ... WHERE matter_id = ?` query
  actually removed every row (including any WAL/journal remnants a
  cross-cutting single-file design would need separate care to purge). This
  also bounds the blast radius of any bug in matter-scoping logic to a
  single file's contents rather than a shared database.

### Cross-matter collision risk (why isolation alone isn't sufficient)

Even with correct matter scoping, the fuzzy-matching threshold itself is a
privacy-relevant parameter, not just a recall/precision tuning knob. Inside
one matter, `link()`'s 0.82 `token_set_ratio` threshold governs whether "Mr.
Doe" pre-redacts as the same person as "John Doe" from an earlier document
*in that same matter* — a false merge here is a redaction-quality bug
(under- or over-redaction within one client's own document set). A false
merge *were* matter scoping ever bypassed or misconfigured would instead be
a cross-client information leak (Client B's document gets pre-redaction
suggestions seeded from Client A's names). This is an argument for the
matter boundary being enforced at the storage/query layer (a `matter_id`
that is structurally required to even construct a lookup, as noted above)
rather than only at the UI layer, so that a UI bug cannot become a
confidentiality bug.

### Should this be opt-in

Yes — this should default OFF, be opt-in per matter (or globally, with a
per-matter override to disable), and be clearly disclosed at the point of
opt-in what is retained (normalized names/orgs/brands and which documents
they came from, not document content or full text), where it's stored
(a local path the user can see and delete), and that it persists across
app sessions and documents, unlike everything else the app does today. This
mirrors the existing pattern in the app of treating retention as
exceptional and explicit rather than default: metadata scrubbing
(`MetadataCleaningSettings`) and the scrub-report mechanism in
`pipeline.py` already default toward being conservative about what's
written where, and `docs/SECURITY.md` already frames "unintended retention
of PII" as a first-class threat category the project watches for in its own
code — this feature is the first one that would make *intended* retention
of PII part of the product, which is exactly why it should require an
explicit, informed opt-in rather than shipping as an always-on default.

A practical minimum for the opt-in flow: surface the matter concept
explicitly (name it, let the user create/select one before this feature
does anything), show what's stored in plain language, and provide a visible
"clear this matter's entity history" action in the same UI surface where
the user manages the matter — not buried in a settings submenu — given that
the data being retained is exactly the kind of information (who is named in
a client's legal documents) this tool exists to redact away.

## Scoped-down MVP recommendation

Given the above, the smallest version of this feature that is worth
building — after human sign-off on the retention-model change itself — is:

1. **Matter as an explicit, user-managed concept**, with no code path that
   infers matter membership automatically. This is a prerequisite for
   everything else and is itself the majority of the net-new UI/UX surface
   area, not the matching algorithm.
2. **Fuzzy-lexical cross-document index only** (extend `ClusterTable`'s
   existing `normalize()` + `token_set_ratio` approach with a persistent,
   matter-scoped backing store), explicitly deferring semantic/embedding
   matching to a later phase. This reuses validated matching logic and adds
   zero new inference cost or native-dependency signing burden.
3. **SQLite, one file per matter**, using the stdlib `sqlite3` module — no
   new third-party dependency, no server process, trivially deletable per
   matter, consistent with `pyproject.toml`'s currently minimal dependency
   footprint.
4. **Opt-in, off by default**, with an explicit, visible "clear this
   matter" action, and matter scoping enforced as a structural precondition
   in the lookup/write-back code path (not just filtered in the UI), so a
   UI bug cannot become a cross-client confidentiality bug.
5. **Pre-redaction suggestions surfaced for confirmation, not silently
   auto-applied**, at least for the MVP: when a new document's span matches
   a cross-document alias, treat it as a high-confidence candidate fed into
   the existing `needs_redaction`/confidence machinery (and, if the
   interactive review design from the sibling "On-the-fly Interactive
   Redaction Mode" backlog item ships first, as a natural candidate to
   surface there) rather than a silent, unreviewable auto-redact — cross-*
   document* corroboration is a strong signal, but it is a different kind of
   evidence than within-document repetition, and the first version of this
   feature should let a human confirm that the link the tool made across
   two separate documents is actually correct before it changes redaction
   output.

Explicitly out of scope for the MVP: semantic/embedding-based matching, any
form of automatic matter inference, cross-*matter* matching of any kind, and
silent auto-redaction based solely on a cross-document match.
