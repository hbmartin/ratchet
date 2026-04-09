# MEGA-Code Local Runtime Architecture

This document describes the local-first runtime introduced in the
`Implement local MEGA-Code runtime` change set. It is intended for engineers
working on the OSS plugin codebase and focuses on implementation details,
state flow, storage, and extension points.

## 1. Goals

The current OSS runtime is built around a single design decision:

- `MEGA-Code` operates as a local runtime by default.
- The MEGA service is not required for normal pipeline or curation flows.
- User-controlled provider keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) are used
  for embeddings and optional generation.
- Local execution persists enough state to support:
  - asynchronous pipeline runs,
  - cross-process status polling,
  - stop requests,
  - local curation over previously distilled knowledge,
  - a feedback loop that changes later retrieval results.

The implementation is intentionally split into a small set of responsibilities:

- the `client` layer owns user-facing CLI contracts and stable data locations,
- the `pipeline` layer owns local execution, distillation, retrieval, and
  runtime state,
- the filesystem still stores rendered artifacts for inspection and install,
  while SQLite stores normalized runtime state and retrieval metadata.

## 2. High-Level System Model

The local runtime can be understood as five connected loops:

1. **Collection / ingest**
   - session data is normalized into `TurnSet` objects,
   - `upload_trajectory()` persists those turnsets locally.

2. **Asynchronous extraction**
   - `trigger_pipeline_run()` creates a run record and spawns a detached worker,
   - the worker distills local sessions into:
     - pending skills,
     - pending strategies,
     - PCR fragments.

3. **Persistence**
   - rendered artifacts are written to file trees for human review and install,
   - normalized state is written to SQLite.

4. **Retrieval / curation**
   - `wisdom_curate()` ranks PCR fragments via hybrid semantic + lexical scoring,
   - dependencies are expanded,
   - an ordered cheatmap is assembled.

5. **Feedback**
   - `wisdom_feedback()` stores curation feedback locally,
   - fragment feedback scores are updated,
   - subsequent retrievals see that updated signal.

## 3. Module Map

### 3.1 New local runtime package

The local runtime lives under `mega_code/pipeline/`.

- `mega_code/pipeline/__init__.py`
  - exports `MegaCodeLocal`.

- `mega_code/pipeline/local_client.py`
  - canonical local client implementation,
  - implements the API protocol surface:
    - trajectory ingest,
    - async run trigger,
    - status/output lookup,
    - stop,
    - active run listing,
    - local curation,
    - local feedback,
    - local skill enhancement save.

- `mega_code/pipeline/store.py`
  - SQLite-backed runtime state store,
  - owns schema initialization,
  - owns pipeline run state,
  - owns artifact/PCR persistence,
  - owns curation and feedback persistence.

- `mega_code/pipeline/runtime.py`
  - pure runtime logic,
  - session loading,
  - heuristic distillation,
  - PCR creation,
  - hybrid retrieval,
  - cheatmap generation.

- `mega_code/pipeline/llm.py`
  - provider abstraction for embeddings and generation,
  - Gemini REST client,
  - OpenAI REST client,
  - deterministic fake provider for tests.

- `mega_code/pipeline/worker.py`
  - detached worker entrypoint,
  - looks up a persisted run,
  - executes local distillation,
  - writes terminal state back to SQLite.

### 3.2 Existing client modules affected

- `mega_code/client/api/__init__.py`
  - now always resolves to local mode,
  - lazily imports `MegaCodeLocal` to avoid import cycles.

- `mega_code/client/api/protocol.py`
  - now includes `wisdom_curate()` and `wisdom_feedback()` in the shared client protocol.

- `mega_code/client/cli.py`
  - now treats local mode as canonical,
  - no longer gates pipeline or curation commands on `MegaCodeRemote`.

- `mega_code/client/check_auth.py`
  - no longer checks `MEGA_CODE_API_KEY`,
  - now validates local provider setup instead.

- `mega_code/client/skill_installer.py`
  - can install from local source paths when `SkillRefItem.url` is empty.

- `mega_code/client/run_pipeline.py`
  - wording and mode semantics now describe a local worker, not a server.

## 4. Client and Mode Resolution

### 4.1 Canonical mode

`mega_code.client.api.resolve_mode()` now always returns `"local"`.

Behavior:

- explicit `remote` arguments are ignored,
- `MEGA_CODE_CLIENT_MODE=remote` is ignored,
- a warning is logged when callers still try to select remote mode.

This is intentional. The runtime no longer asks the caller to make a mode
decision for normal OSS behavior.

### 4.2 Lazy import strategy

`create_client()` lazy-imports `MegaCodeLocal` inside the function body.

Reason:

- `profile.py` depends on protocol models,
- the API package imports the client factory,
- eager local-client import created a `profile -> api -> local_client -> profile`
  cycle.

The lazy import keeps module initialization acyclic while preserving the same
public API.

## 5. Runtime State and Storage

### 5.1 Storage layout

The local runtime uses the existing `data_dir()` root:

- default: `~/.local/share/mega-code`
- override: `MEGA_CODE_DATA_DIR`

Key subpaths used by the local runtime:

- `local-runtime.sqlite3`
  - SQLite database for runtime state.

- `projects/{project_id}/{session_id}/turns.jsonl`
  - normalized stored turnsets when trajectories are uploaded without a richer
    collector session directory.

- `knowledge/skills/{skill_name}/SKILL.md`
  - rendered local skill sources used by curation/install.

- `knowledge/strategies/{strategy_name}/{strategy_name}.md`
  - rendered local strategy sources.

- existing pending/install locations remain unchanged:
  - `data/pending-skills/...`
  - `data/pending-strategies/...`
  - `skills/...`

### 5.2 SQLite schema

The schema is created by `LocalStore._init_schema()`.

#### `trajectories`

Purpose:
- index normalized uploaded turnsets by session.

Fields:
- `session_id`
- `project_id`
- `session_dir`
- `turn_count`
- `metadata_json`
- `updated_at`

#### `pipeline_runs`

Purpose:
- track lifecycle and cross-process state for async local runs.

Fields:
- `run_id`
- `project_id`
- `project_path`
- `session_id`
- `steps_json`
- `model`
- `include_claude`
- `include_codex`
- `limit_value`
- `concurrency`
- `status`
- `progress_json`
- `outputs_json`
- `error`
- `pid`
- `requested_stop`
- `started_at`
- `completed_at`

This table is what allows:
- `pipeline-status`,
- `pipeline-stop`,
- `run_pipeline.py` polling across separate process boundaries.

#### `artifacts`

Purpose:
- persist distilled skills and strategies as normalized records.

Fields:
- `artifact_id`
- `run_id`
- `project_id`
- `session_id`
- `artifact_type`
- `name`
- `version`
- `content`
- `metadata_json`
- `source_path`
- `created_at`
- `embedding_json`

Rendered content is duplicated on disk and in the DB. This is deliberate:

- files are operator-facing and install-friendly,
- DB rows are retrieval- and provenance-friendly.

#### `pcr_fragments`

Purpose:
- store atomic retrievable knowledge units.

Fields:
- `fragment_id`
- `artifact_id`
- `run_id`
- `project_id`
- `name`
- `procedure`
- `context`
- `resultant`
- `constraints`
- `evidence_refs_json`
- `source_artifact`
- `dependency_ids_json`
- `feedback_score`
- `created_at`
- `embedding_json`
- `lexical_text`

This table is the core of the local curation system.

#### `curation_sessions`

Purpose:
- persist generated curations for later resume and feedback linkage.

Fields:
- `session_id`
- `query`
- `curation`
- `skills_json`
- `wisdoms_json`
- `token_count`
- `cost_usd`
- `created_at`
- `status`

#### `curation_feedback`

Purpose:
- persist textual feedback linked to a curation session.

Fields:
- `feedback_id`
- `session_id`
- `feedback_text`
- `created_at`

## 6. Provider Integration

### 6.1 Selection order

Provider selection is implemented in `mega_code.pipeline.llm.create_llm_client()`.

Resolution order:

1. `MEGA_CODE_TEST_FAKE_LLM=1`
   - deterministic test provider.
2. `GEMINI_API_KEY`
   - Gemini REST provider.
3. `OPENAI_API_KEY`
   - OpenAI REST provider.
4. otherwise:
   - raise a local setup error.

### 6.2 Fake provider

`FakeLocalLLM` is used in tests.

Properties:
- deterministic hash-based embeddings,
- no network dependency,
- simple synthetic generation.

Why it exists:
- lifecycle tests must verify retrieval and feedback behavior without relying
  on external APIs,
- test coverage should validate ranking and persistence, not provider uptime.

### 6.3 Gemini provider

`GeminiLocalLLM` uses:

- embeddings:
  - `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent`
- generation:
  - `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`

Implementation notes:
- embeddings are normalized to unit length before storage,
- dimension is constrained to a fixed local value (`128`) so vectors stay
  lightweight in SQLite,
- generation is intentionally low-temperature because it is used only as a
  local helper surface, not as an autonomous planner.

### 6.4 OpenAI provider

`OpenAILocalLLM` uses:

- embeddings:
  - `POST https://api.openai.com/v1/embeddings`
- generation:
  - `POST https://api.openai.com/v1/responses`

Implementation notes:
- embeddings use `text-embedding-3-small`,
- dimensions are pinned to the same local embedding dimension for compatibility
  with the SQLite store,
- response parsing intentionally extracts plain text only.

## 7. Trajectory Ingest

### 7.1 Entry point

The canonical ingest method is:

- `MegaCodeLocal.upload_trajectory(turn_set, project_id)`

Behavior:

1. resolves or creates a local session directory,
2. writes `turns.jsonl` using the existing `save_turns_jsonl()` helper,
3. upserts a `trajectories` row,
4. returns `UploadResult(status="accepted")`.

### 7.2 Why local ingest still matters

Even though the runtime is local, ingest remains a first-class operation
because it solves two different problems:

- collector hooks can persist normalized session knowledge immediately,
- later background runs can operate on those normalized turnsets without
  reconstructing the original session again.

`runtime._load_turnset_from_session_id()` first checks the local trajectory
store and only falls back to collector history when needed.

## 8. Pipeline Run Lifecycle

### 8.1 Triggering a run

`MegaCodeLocal.trigger_pipeline_run()` is async to preserve the existing
client contract.

Behavior:

1. check `pipeline_runs` for an active run on the same `project_id`,
2. if an active run exists and `force=False`:
   - raise `httpx.HTTPStatusError(409)` so existing CLI conflict handling keeps
     working,
3. if `force=True`:
   - stop the existing run first,
4. create a new run row with `status='queued'`,
5. spawn a detached worker:
   - `python -m mega_code.pipeline.worker --run-id <run_id>`
6. store the worker `pid`,
7. return `TriggerPipelineResult(..., status='queued')`.

### 8.2 Worker process

`mega_code.pipeline.worker` is intentionally small.

It does three things:

1. marks the run as started and stores its PID,
2. executes `run_local_pipeline(run_id)`,
3. writes terminal state:
   - `completed`,
   - `failed`,
   - or `stopped`.

### 8.3 Status reconciliation

`LocalStore.get_pipeline_status()` calls `_reconcile_row()`.

This is important because detached local workers can disappear without writing a
terminal state, for example due to environment issues or process death.

Reconciliation rule:

- if a run is still `queued` or `running` but its `pid` is no longer alive,
  the row is rewritten to:
  - `status='failed'`
  - `error='Local worker exited before finishing.'`

This keeps polling deterministic and prevents hung `running` rows from
surviving forever.

### 8.4 Stop semantics

Stopping is cooperative with a hard signal fallback.

`stop_pipeline()`:

1. sets `requested_stop=1`,
2. marks the row `stopped`,
3. sends `SIGTERM` to the recorded `pid` when possible.

The worker also checks `store.is_stop_requested(run_id)` during distillation so
it can stop gracefully between sessions.

## 9. Session Loading

### 9.1 Input selection

The runtime supports two main input modes:

- single session mode
  - identified by `session_id`,
- project mode
  - identified by `project_path`,
  - optionally enriched via:
    - `include_claude`,
    - `include_codex`,
    - `limit`.

### 9.2 Loading path

`load_turnsets_for_run()` uses:

- locally stored turnsets for uploaded sessions when available,
- otherwise existing history loaders:
  - `load_sessions_from_project(...)`,
  - `_session_to_turnset(...)`.

This reuse is important because it avoids inventing a second session parsing
stack just for the local pipeline.

## 10. Distillation Strategy

The current OSS distillation logic is intentionally heuristic and deterministic.

It is not attempting to fully reproduce a proprietary extraction pipeline.
Instead, it provides a concrete local implementation that preserves the core
MEGA-Code behavior:

- distill reusable artifacts,
- decompose them into atomic retrievable units,
- feed them back into later work.

### 10.1 Skill naming

`_derive_skill_name()`:

- tokenizes commands, tool names, and content,
- removes stop words,
- takes top keywords,
- generates a kebab-case skill name.

### 10.2 Step extraction

`_collect_steps()` scans turns in priority order:

- commands,
- tool calls,
- assistant reasoning.

Each step stores:
- kind,
- label,
- source turn id,
- evidence snippet,
- error flag.

The resulting step list is:
- deduplicated,
- capped,
- guaranteed non-empty.

### 10.3 Skill rendering

`_build_skill_markdown()` constructs:

- frontmatter,
- summary,
- workflow section,
- basic guardrails.

The file is not intended to be a perfect human-authored skill. It is intended
to be:

- installable,
- inspectable,
- retrievable,
- traceable to source evidence.

### 10.4 Strategy rendering

`_build_strategy_markdown()` focuses on:

- repeated choices,
- fallback behavior,
- error-aware correction patterns.

When error steps exist, they are explicitly encoded into the strategy.

### 10.5 PCR fragment creation

Each step becomes a PCR fragment with:

- `procedure`
  - the normalized step label,
- `context`
  - project path, branch, model,
- `resultant`
  - evidence snippet from the session,
- `constraints`
  - simple execution guardrails,
- `evidence_refs`
  - session id and turn id,
- `dependency_ids`
  - previous step fragment when a dependency chain exists,
- `embedding`
  - provider-generated vector,
- `lexical_text`
  - flattened text used for lexical ranking.

The result is a small dependency-aware procedure graph per distilled skill.

## 11. Artifact Persistence

After distillation, the runtime writes both:

- pending outputs for normal MEGA-Code review flow,
- normalized artifacts and PCR fragments into SQLite.

### 11.1 File persistence

`LocalStore.write_source_tree()` writes:

- skills:
  - `knowledge/skills/{skill_name}/SKILL.md`
- strategies:
  - `knowledge/strategies/{strategy_name}/{strategy_name}.md`

These paths are later exposed through `SkillRefItem.path` in local curation.

### 11.2 Pending outputs

The worker returns an `OutputsResult` with:

- `pending_skills`
- `pending_strategies`

The existing `run_pipeline.py` flow then continues to save these into the
established pending directories via `save_outputs_to_pending()`.

This preserves the review/install UX already used elsewhere in the repo.

## 12. Local Curation and Retrieval

### 12.1 Entry point

`MegaCodeLocal.wisdom_curate()` delegates to `runtime.curate_local_wisdom()`.

### 12.2 Candidate corpus

Candidates are loaded from `pcr_fragments`, joined with their parent artifacts.

Each fragment carries two retrieval-friendly representations:

- a vector embedding,
- a lexical text field.

### 12.3 Ranking algorithm

The current local ranking pipeline is hybrid:

1. embed the query,
2. compute cosine similarity against fragment embeddings,
3. tokenize lexical text and compute BM25-style scores,
4. normalize semantic and lexical scores independently,
5. add lightweight boosts for:
   - feedback,
   - recency,
   - provenance (`source_path` exists),
6. sort descending by final score.

Current weighting:

- semantic: `0.5`
- lexical: `0.3`
- feedback: additive
- recency: additive
- provenance: additive

This is intentionally simple and fully local. The goal is exact, debuggable
retrieval, not ANN scale.

### 12.4 Dependency expansion

After selecting top seeds, dependency ids are collected and included as needed.

Ordering is produced by a depth-first visit over dependency ids, giving a
deterministic dependency-first output ordering suitable for cheatmap assembly.

### 12.5 Cheatmap generation

The current curation document contains:

- problem statement,
- workflow heading,
- short overview,
- ordered steps,
- per-step:
  - procedure,
  - context,
  - resultant,
  - score.

This is a local analogue of the cheatmap concept described in the README and
research notes.

### 12.6 Skill references

`SkillRefItem` is used in local mode with:

- `name`
- `path`
  - local source path for the rendered skill,
- `url=""`

The installer now interprets this correctly and copies from local source.

## 13. Feedback Loop

### 13.1 Feedback persistence

`wisdom_feedback()` stores:

- a `curation_feedback` row,
- updates the associated `curation_sessions` row to `completed`.

### 13.2 Fragment score updates

Each curation stores the selected fragment ids as `wisdoms_json`.

When feedback arrives:

- each referenced fragment receives a feedback delta,
- the delta is currently inferred heuristically from text:
  - strong positive wording or high ratings increase score,
  - negative wording or low ratings decrease score,
  - otherwise a small positive default is applied.

This is intentionally lightweight but functional. It makes the loop
stateful without needing a second model pass.

## 14. Skill Installation

The original installer assumed server-provided HTTPS ZIP URLs.

The local runtime changes this by allowing:

- `SkillRefItem.url` to be empty,
- `SkillRefItem.path` to point at a local skill source tree.

New install behavior:

- if `path` exists locally and contains `SKILL.md`:
  - copy the tree into `{data_dir}/skills/{name}/`,
- else if `url` exists:
  - use the old HTTPS ZIP path,
- else:
  - return `skipped`.

This allows curation/install to work entirely offline apart from provider API
calls for embeddings/generation.

## 15. CLI and User-Facing Behavior Changes

### 15.1 Setup / auth

`check_auth.py` is now a local setup gate.

It checks:

- `GEMINI_API_KEY`
- or `OPENAI_API_KEY`

It does not check:

- `MEGA_CODE_API_KEY`
- server reachability.

### 15.2 Login

The `login` command is now a legacy shim that prints local configuration
instructions instead of attempting OAuth.

### 15.3 Pipeline commands

`pipeline-status`, `pipeline-stop`, `wisdom-curate`, and `wisdom-feedback`
now operate against the protocol client surface directly and no longer require
`MegaCodeRemote`.

## 16. Testing Strategy

### 16.1 New tests

Added:

- `tests/test_local_runtime.py`
  - client factory returns local runtime,
  - ingest persists `turns.jsonl`,
  - async local pipeline lifecycle completes,
  - outputs contain pending skills and strategies,
  - curation returns local skill references,
  - feedback changes later retrieval score,
  - stop status persists,
  - local-path install works.

- `tests/test_local_setup.py`
  - local setup passes with provider keys,
  - local setup fails without them.

### 16.2 Existing tests preserved

Remote-client unit tests were left intact because:

- they still validate the legacy remote implementation in isolation,
- they do not block local-first behavior,
- they continue to protect payload construction and status parsing logic for
  code that may still reuse those modules.

## 17. Tradeoffs and Known Limitations

This implementation is intentionally pragmatic. It does not attempt to solve
every research aspiration described in the docs.

Current limitations:

- distillation is heuristic, not learned,
- PCR generation is step-derived rather than model-generated,
- feedback weighting is heuristic,
- dependency graphs are shallow and mostly sequential,
- retrieval is exact and SQLite-backed, not ANN-backed,
- generation is only lightly used in the current local pipeline.

These are acceptable for the current OSS objective because the implementation
already provides:

- a real local runtime,
- async runs,
- durable state,
- retrievable PCR fragments,
- local cheatmap generation,
- a working feedback loop.

## 18. Recommended Extension Points

If the local runtime is extended later, the most natural places are:

### Better distillation

File:
- `mega_code/pipeline/runtime.py`

Possible improvements:
- segment traces into richer episode boundaries,
- use provider generation to synthesize higher-quality skill bodies,
- generate multiple strategy variants from repeated sessions.

### Better retrieval

Files:
- `mega_code/pipeline/runtime.py`
- `mega_code/pipeline/store.py`

Possible improvements:
- separate indexes for procedure/context/resultant,
- richer dependency edge types,
- reranking pass using provider generation,
- explicit artifact-level and fragment-level negative feedback.

### Better feedback

File:
- `mega_code/pipeline/store.py`

Possible improvements:
- parse structured rating fields,
- attribute feedback by step instead of whole curation,
- decay old feedback over time.

### Background execution robustness

Files:
- `mega_code/pipeline/local_client.py`
- `mega_code/pipeline/worker.py`

Possible improvements:
- platform-specific detached execution handling,
- lock files to prevent duplicate workers for the same run id,
- worker heartbeats instead of PID-only liveness.

## 19. Operational Summary

The runtime should be mentally modeled as:

- **collector data in**
- **turnsets normalized**
- **local worker distills**
- **artifacts and PCR stored locally**
- **curation retrieves from SQLite + files**
- **feedback updates retrieval state**

That is the core architecture introduced by the current local runtime.
