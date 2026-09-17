---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0008
title: Options for a persistent semantic index of the jcode source tree
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.OPTIONS
version: "2026-09-17"
---

# Persistent Semantic Index for the jcode Source Tree: Options Report

Date: 2026-09-17
Scope: `/home/d/dev_env/jcode` (Rust workspace: `crates/*` + `src/`)
Goal: realistic, concrete options for a *semantic* index over the repo that
**persists** (survives restarts, reusable across runs/sessions, not rebuilt from
scratch each time).

All repo claims are cited `file:line`. Anything that could not be verified is
marked **UNVERIFIED** rather than guessed.

---

## 1. What already exists in jcode (the cheap raw materials)

### 1.1 A local ONNX embedding model, always available, no network

jcode ships a bundled local sentence embedder: `all-MiniLM-L6-v2`, run through
`tract_onnx` in the `jcode-embedding` crate.

- Model name constant: `MODEL_NAME: &str = "all-MiniLM-L6-v2"` — `crates/jcode-embedding/src/lib.rs:10`
- Model + tokenizer fetched once from HuggingFace and cached on disk at
  `~/.jcode/models/all-MiniLM-L6-v2/` — `crates/jcode-base/src/embedding.rs:402-403`
  (`models_dir()` = `jcode_dir()?.join("models").join(MODEL_NAME)`).
- Downloads only if `model.onnx` / `tokenizer.json` are missing — `crates/jcode-embedding/src/lib.rs:124-129`.
- The process-wide facade exposes `embed()`, `embed_batch()` and a cross-encoder
  reranker — `crates/jcode-base/src/embedding.rs:106-111,174`.
- **This is a true embedding model that runs locally with zero API key and no
  network after first download.** It is the cheapest semantic primitive that
  already exists in-tree.

### 1.2 A pluggable `EmbeddingBackend` trait with local + remote backends

`crates/jcode-base/src/embedding_backend.rs` abstracts a vector source behind
one trait with a stable `model_id()` used to gate cross-model comparisons.

- Trait `EmbeddingBackend` (model_id, dim, embed_raw, query/passage formatting,
  batch `embed_passages`) — `embedding_backend.rs:33-74`.
- `LocalOnnxBackend` (no network, always available, default) — `embedding_backend.rs:81-99`.
- `OpenAiEmbeddingBackend` (OpenAI / OpenAI-compatible `/v1/embeddings`, batch
  POST) — `embedding_backend.rs:101-268`.
- `active_backend()` resolves remote only if opted in via config
  `agents.memory_embedding_backend = "openai"` AND an embeddings credential
  resolves; otherwise it falls back to local — `embedding_backend.rs:278-283`,
  `openai_backend_from_config()` `embedding_backend.rs:287-304`.
- **Reusable building block:** any new semantic index can call
  `embed_query_active` / `embed_passage_active` (`embedding_backend.rs:324-336`)
  without caring whether local or remote is wired up.

### 1.3 The memory subsystem already persists embeddings on disk

`MemoryEntry` carries persisted embedding vectors and a model tag
— `crates/jcode-memory-types/src/lib.rs:233-283`, notably `embedding:
Option<Vec<f32>>` (`...:266-269`) and `embedding_model: Option<String>`
(`...:276-282`).

Those graphs persist as JSON:

- Global memory: `~/.jcode/memory/global.json` — `crates/jcode-base/src/memory.rs:360`
- Per-project memory: `~/.jcode/memory/projects/<project-hash>.json` — `memory.rs:273-274`
- Graph save paths: `save_project_graph` / `save_global_graph` — `memory.rs:1778,1789`
- In-process graph cache with **mtime invalidation** — `crates/jcode-base/src/memory/cache.rs:32-45`
  (`graph_mtime` compared; on change the entry is dropped and rebuilt).
- `jcode_dir()` is `$JCODE_HOME` or `~/.jcode` — `crates/jcode-storage/src/lib.rs:150-161`.

**Implication:** jcode *already* persists embeddings durably on disk and already
has the caching/invalidation plumbing. What is missing is a bridge that indexes
*source files* (rather than short memory passages) and persists that separately.

### 1.4 An existing on-disk incremental index with mtime+size invalidation (the best template)

`crates/jcode-app-core/src/tool/session_search_index.rs` is a durable,
incrementally-updated, on-disk token-Bloom index used by `session_search`. It is
the single best in-repo template for "persistent index that cheaply updates."

- Per-entry identity = `(key, mtime_ms, size)` — `IndexFileSpec` `session_search_index.rs:69-75`.
- On rebuild, entries whose identity is unchanged are reused as-is; only new or
  modified files are re-read/re-tokenized — `...:388-400`.
- `stat_ms_size()` helper returns `(mtime_ms, size)` — `...:482-495`.
- Binary on-disk format with magic + version; version skew ⇒ rebuild from
  scratch — `...:32-36`, `save` `...:245-272`, `load` `...:274-321`.
- Atomic write via tempfile + rename — `...:268-270`.
- Parallel rebuild over stale slots — `tokenize_slots_parallel` `...:435-479`.
- Index files live under `~/.jcode/cache/` — `index_dir()` in
  `crates/jcode-app-core/src/tool/session_search.rs:794-797`.

**This is exactly the persistence/invalidation pattern a semantic index needs**:
swap the "token Bloom" payload for embedding vectors, keep the same
`(key, mtime, size)` invalidation, and you get a self-maintaining on-disk
semantic index.

### 1.5 SQLite is already a persistence precedent

`rusqlite` (SQLite) is used for a durable cross-process metadata index:
`crates/jcode-base/src/recent_session_index.rs` writes WAL-mode SQLite to
`~/.jcode/session-metadata-v1.sqlite3`:

- Connection open with `PRAGMA journal_mode=WAL; synchronous=NORMAL` — `...:46-58`.
- Online-additive migration pattern — `...:62-65`.
- `rusqlite` also present in `crates/jcode-base/src/model_usage.rs` and
  `crates/jcode-base/src/auth/cursor.rs` (grep, names only; no secrets read).

**Implication:** jcode already depends on rusqlite. A SQLite-backed vector index
(or plain SQLite with a simple row-per-file layout) needs no new C dependency.

### 1.6 Lexical retrieval that already exists (the non-semantic baseline)

- `session_search`: token-Bloom prefilter + full-content verification.
- `agentgrep` tool: shells out to ripgrep with literal/regex modes, glob file-type
  filtering, and optional harness-context JSON output — `agentgrep.rs:206,219,231,253`
  (`regex`/query/glob / "shells out to ripgrep"); `agentgrep/args.rs` resolves
  scope; `agentgrep/context.rs` writes `AgentGrepHarnessContext`.
- `jcode_docs` tool: searches bundled markdown docs compiled in at `OUT_DIR` —
  `crates/jcode-app-core/src/tool/jcode_docs.rs:9-10,31-40` (docs embedded at
  build time, not a runtime index).

These are lexical (grep/BM25-style) retrieval. Useful as a cheap pre-filter to
feed a semantic re-ranker (see Section 4).

---

## 2. Option space

Legend for each option: what persists · where on disk · invalidation · cost ·
implementation effort in jcode.

### 2a. Reuse jcode's embedding backend + memory graph to index source files

Description: treat each source file as a memory passage, run it through the
existing local MiniLM backend, and store vectors in the existing memory-graph
JSON (or a parallel graph sharing the same store/cache code).

- What persists: embedding vectors + model tag, inside `MemoryEntry`
  (`embedding`, `embedding_model` — `jcode-memory-types/src/lib.rs:266-282`).
- Where: `~/.jcode/memory/global.json` and/or `~/.jcode/memory/projects/<hash>.json`
  ([1.3](#13-the-memory-subsystem-already-persists-embeddings-on-disk),
  `memory.rs:360,273-274`).
- Invalidation: relies on the graph being regenerated when the file changes.
  The existing graph cache is mtime-gated in-process only
  (`memory/cache.rs:32-45`) and is **not** per-source-file identity — memory
  graph invalidation is by whole-graph mtime, not per-file `(mtime,size)`. A
  per-file incremental path is **not** present today for arbitrary source files.
- Cost: local MiniLM inference per file at build; storage = JSON graphs (vector
  text, not compact binary). Cheap on GPU-free host (CPU MiniLM), a few MB for a
  repo this size.
- Effort: low/medium. The backend (`embed_query_active`) and the persistence
  (`save_*_graph`) exist; what's missing is (1) a source-file→`MemoryEntry`
  ingester and (2) per-file invalidation granularity (reuse the
  session_search_index `(key,mtime,size)` scheme).
- Verdict: cheapest to **start**, but the memory-graph shape is not designed for
  many large file passages and lacks per-file incremental rebuild. Good for a
  v1; likely want 2b for production.

### 2b. On-disk embedding cache keyed by `(path, mtime, size)` reusing the session_search_index pattern ★ recommended

Description: a dedicated incremental on-disk index of source files → embedding
vectors, copying the proven `session_search_index` design ([1.4](#14-an-existing-on-disk-incremental-index-with-mtime-size-invalidation-the-best-template))
but storing vectors instead of token Bloom bits.

- What persists: per-file embedding vectors (+ model id, dim, text hash for
  optional re-verify), with the full source text **not** required after build
  (store path+vector; re-read file only when identity changed).
- Where: `~/.jcode/cache/` (same dir as the session-search index —
  `session_search.rs:794-797`), e.g. `~/.jcode/cache/source_semantic_v1.bin`.
- Invalidation: file change = different `(mtime_ms, size)` ⇒ that file's vector
  re-embedded; unchanged files are reused verbatim (`IndexFileSpec` reuse logic,
  `session_search_index.rs:388-400`). Versioned magic ⇒ full rebuild on format
  bump (`session_search_index.rs:32-36`). `stat_ms_size` (`...:482-495`) is the
  exact helper to reuse.
- Cost: MiniLM CPU inference only for changed files at rebuild; cold build
  embeds the whole repo once (a few hundred files, seconds/minute on CPU).
  Storage: `f32*dim` (~384 floats/file for MiniLM) per file; tiny (KB range).
- Effort: medium. This is a new tool + index struct, but it is a near
  copy-paste/adaptation of `TokenHashIndex` (bloom) → `VectorIndex` (Vec<f32> +
  optional ANN). Reuse `build_or_update`, `stat_ms_size`, `INDEX_THREADS`
  parallelism, tempfile+rename atomic write.
- Verdict: the best value. Reuses the highest-leverage existing machinery
  (embedding backend + the exact persistence/invalidation pattern), gives true
  semantic retrieval, and is truly persistent across restarts.

### 2c. SQLite-backed vector index / on-disk embedding cache

Description: same as 2b but persist rows in SQLite (WAL) instead of a custom
binary format, optionally using a vector extension for ANN search.

- What persists: rows of `(path, mtime_ms, size, model_id, vector)` in a SQLite
  DB; optionally an HNSW/brute-force vector table if a vector extension is
  enabled.
- Where: `~/.jcode/...sqlite3` (precedent: `recent_session_index.rs:42`).
- Invalidation: same `(path, mtime, size)` per-row logic as 2b; WAL mode and
  cross-process access are already demonstrated (`recent_session_index.rs:46-58`).
- Cost: same embedding cost as 2b; storage slightly larger than a compact binary
  but still trivial.
- Effort: low-to-medium if plain (no extension); medium-to-high if you add a
  vector extension (needs a vendored/build-time SQLite with the extension, or
  an external SQLite, plus new Rust dependency). A vector extension is
  **UNVERIFIED** to load in this build; the plain rows-and-knn-scan approach is
  safe with the existing `rusqlite` dep.
- Verdict: good when cross-process/daemon visibility and ad-hoc SQL matter; the
  custom binary of 2b is simpler and matches the in-repo precedent more closely.

### 2d. External/local indexers (well-known tooling)

Description: run an external local semantic indexer (e.g. `tree-sitter`-based
+ embeddings, or tools like `codex index`, `ctags`, `ripgrep`-fed ANN stores)
or an external embedding model/API.

- Local embedding **model swap**: `Embedder::load_from_dir` supports loading an
  explicit alternative model dir (`embedding.rs:97-101`), and A/B paths exist for
  `e5-small-v2` and a cross-encoder MiniLM (`jcode-embedding/src/lib.rs:594,617`).
  So dropping a stronger local ONNX model into `~/.jcode/models/<name>/` is
  supported in principle.
- Remote embedding (OpenAI / OpenAI-compatible): already wired through
  `OpenAiEmbeddingBackend` + `openai_backend_from_config()`
  (`embedding_backend.rs:287-304`) — but it is **opt-in** and returns `None`
  (falls back to local) when `OPENAI_API_KEY` is not resolvable
  (`openai_backend_from_config`, `embedding_backend.rs:295-296,278-283`).
  Requires network access and a configured key.
- Well-known external indexers (git-based symbol indexes, vendor ANN stores,
  standalone `--embeddings` CLIs): **none are present in the jcode dependency
  graph** (grep found no tree-sitter/vendor ANN in the tools). Adding one means
  a new binary/dependency and an out-of-process contract.
- Cost: external model = possible network + new credentials; external indexer =
  new install + separate daemon/index lifecycle.
- Verdict: only worth it if the bundled MiniLM dimensionality/quality is
  insufficient, or the operator explicitly prefers an external tool. Higher
  operational cost than 2b for a repo this size. Remote OpenAI is unusable in
  the current environment (see Section 3).

### 2e. Greedy/lexical hybrid (grep + optional embedding rerank)

Description: keep lexical retrieval (`agentgrep`, ripgrep, token-Bloom) as the
fast pre-filter and optionally re-rank the small candidate set with the
embedder. This mirrors what jcode already does for *memory* (hybrid
dense+lexical with listwise rerank — `memory_rerank.rs:1-14`).

- What persists: depends — the grep path needs no index; if vectors are computed
  for a candidate pool they should live in the 2b index.
- Invalidation: lexical has no index to invalidate (ripgrep reads live files);
  2b-style vectors invalidated per-file as in Sections 2b.
- Cost: near-zero for the grep-only tier; adds embedding only on a small
  candidate set at query time (or lazily-cached vectors).
- Effort: low. `agentgrep` already shells out to ripgrep (`agentgrep.rs:253`).
- Verdict: the pragmatic middle ground — cheapest to ship, and for identifier /
  symbol / API-name queries grep is often "enough"; embeddings add recall for
  paraphrase/natural-language queries. **For a semantic index specifically, 2b
  pairs naturally with this as a re-rank layer.**

---

## 3. Credentials / provider availability in this environment

Checked without printing any secret values:

- Local ONNX MiniLM: **available by default, no key, no network after first
  download.** Default config is `memory_embedding_backend = "local"`
  (`crates/jcode-base/src/config/default_file.rs:493`); env override
  `JCODE_MEMORY_EMBEDDING_BACKEND` (`config/env_overrides.rs:422-427`).
- Remote OpenAI embeddings: **not usable right now.** The backend is opt-in and
  requires `OPENAI_API_KEY` resolvable from env or an env-file
  (`embedding_backend.rs:295-296,301-303`). `$OPENAI_API_KEY` is **not set** in
  this environment and no `~/.jcode/*.env` key files were found. Treat remote
  OpenAI as unavailable unless the operator supplies a key.
- Provider/auth catalog surface is broad (auth modules for anthropic, gemini,
  openai/codex, azure, bedrock, openrouter, cursor, copilot, grok —
  `crates/jcode-base/src/auth/*.rs`), but **only the OpenAI/openai-compatible
  route has an embeddings path in the memory/embedding code**
  (`OpenAiEmbeddingBackend`); Anthropic/Gemini/Bedrock etc. are chat routes and
  were not found wired to embeddings in the code surveyed. Marked
  **UNVERIFIED** that any remote chatting provider also exposes an embeddings
  endpoint jcode reuses; the concrete embedding routes are local-MiniLM and
  OpenAI-compatible only.

**Bottom line for recommendations:** the *only* immediately-usable semantic
engine in this environment is the bundled local MiniLM model. Everything below
assumes local embeddings unless the operator later supplies an
OpenAI-compatible key.

---

## 4. RECOMMENDATION (ranked, best value first)

**1. On-disk embedding cache keyed by `(path, mtime, size)` — "2b" (reuse the
`session_search_index` persistence pattern + local MiniLM backend).**
This is both the cheapest path that reuses existing jcode machinery *and* the
highest value. It reuses (a) the already-bundled, keyless local ONNX embedder
(`embedding.rs:402-403`), (b) the pluggable `EmbeddingBackend` +
`embed_query_active` (`embedding_backend.rs:33-74,324-336`), and (c) the exact
proven persistence/incremental-invalidation design of `session_search_index`
(identity reuse `...:388-400`, `stat_ms_size` `...:482-495`, atomic save
`...:268-270`, versioned magic `...:32-36`). It is genuinely persistent
(rebuilds only changed files), needs no network and no new dependencies, and is
a small adaptation (Bloom→Vec<f32>) of code that is already tested and shipped
in jcode. On-disk home: `~/.jcode/cache/`.

**2. SQLite-backed vector rows ("2c", plain rusqlite).**
Nearly as cheap and adds daemon/cross-process visibility and ad-hoc querying
(WAL precedent `recent_session_index.rs:46-58`). Prefer only if cross-process
inspection or SQL maintenance matters more than a compact single-file index;
avoid a vector-extension dependency initially (loading it is UNVERIFIED here).

**3. Memory-graph reuse ("2a").**
Fastest to prototype (existing `MemoryEntry.embedding` + `save_*_graph`), but
not designed for many large file passages and lacks per-file invalidation
granularity; use as a stepping stone to #1, not the long-term home for a source
index.

**4. Memory-style hybrid (lexical pre-filter + embedding re-rank) ("2e").**
Cheapest to ship and great for identifier/symbol queries (grep usually
suffices), but it is only *optionally* semantic and does not by itself build a
persistent semantic index; combine with #1 for the re-rank layer.

**5. External tools / remote embeddings ("2d").**
Highest operational cost and, in this environment, remote OpenAI embeddings are
currently unusable (no `OPENAI_API_KEY`); only consider if the bundled MiniLM
is measurably insufficient or the operator explicitly wants an external
indexer/stronger model.

### Cheapest path that reuses existing jcode machinery (explicit)
Reuse the **bundled local `all-MiniLM-L6-v2` ONNX embedder** (always available,
no key/no network) through the existing **`EmbeddingBackend` trait**, and persist
vectors in a **dedicated on-disk index that adopts the `session_search_index`
`(mtime_ms, size)` per-file incremental-invalidation design**, written under
`~/.jcode/cache/`. That combination = **Option 2b**, and it is the cheapest
fully-persistent, restart-safe, no-new-dependency semantic index available for
this repo.

---

## 5. Notes / unverified

- Whether any remotely-configured chatting provider (Anthropic/Gemini/…) also
  exposes an embeddings endpoint that jcode could reuse was not verified; the
  surveyed embedding routes are local-MiniLM and OpenAI-compatible only.
- Whether a SQLite vector extension can be loaded in this build was not
  verified; the plain-rows + KNN-scan variant is safe with the existing
  `rusqlite` dependency.
- No change to any source file was made; this report is informational only.
