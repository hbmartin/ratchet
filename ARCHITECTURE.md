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
  - a feedback loop that changes later retrieval results,
  - provenance-aware validation, trust, and safety gating before prior knowledge
    can influence future sessions.

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
   - the worker runs a clustered closed-loop distiller that:
     - extracts session traces with keywords, tools, paths, env fingerprints,
       error windows, and correction windows,
     - clusters traces by project/anchor similarity,
     - runs success and error analyst LLM passes per cluster,
     - consolidates proposals into canonical workflows, strategies, and memory
       fragments,
     - synthesizes operators from the consolidated workflow,
     - persists PCR fragments from consolidated memory fragments.

3. **Persistence**
   - rendered artifacts are written to file trees for human review and install,
   - normalized state is written to SQLite, including governance metadata on
     every artifact, fragment, and operator.

4. **Retrieval / curation**
   - `wisdom_curate()` runs hybrid seed retrieval across procedure/context/outcome
     facets plus contextual lexical matching,
   - seeds are fused with reciprocal-rank fusion (RRF),
   - structural expansion uses personalized PageRank over the operator graph,
   - reranking combines seed, structural, facet, contextual, env-match, support,
     recency, provenance, and reliability signals,
   - conflict suppression removes mutually exclusive operators,
   - topological wave planning produces dependency-respecting execution waves
     with compact per-step context packages.

5. **Feedback**
   - `wisdom_feedback()` stores per-step causal feedback,
   - operator reliability metrics (helped/hurt/unused/missing counts, calibration
     error, Brier score) are aggregated per operator,
   - `feedback_score` is a derived compatibility score from empirical evidence,
   - subsequent retrievals consult reliability when computing predicted success,
     abstention probability, and dynamic governance gate eligibility.

## 3. Module Map

### 3.1 Local runtime package

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
  - owns artifact/PCR/operator persistence,
  - owns provenance, validation, and trust metadata,
  - owns curation and feedback persistence,
  - owns operator reliability aggregation and derived metrics.

- `mega_code/pipeline/runtime.py`
  - pure runtime logic,
  - session trace extraction (`_build_session_trace`, `_build_session_traces`),
  - trace clustering (`_cluster_traces`, `_connected_components`),
  - analyst LLM passes (`_run_analyst_pass`),
  - proposal grouping (`_group_proposals`),
  - consolidator LLM pass (`_run_consolidator_pass`),
  - cluster-level distillation (`distill_cluster`),
  - single-session fallback distillation (`distill_session`),
  - operator synthesis (`_operator_payloads`),
  - PCR fragment creation (`_build_pcr_payloads`),
  - governance payload construction (`_build_governance_payload`),
  - operator-graph retrieval with RRF, PageRank, reranking, wave planning,
  - safety-gated reuse and dynamic governance evaluation,
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

### 3.2 Client modules

- `mega_code/client/api/__init__.py`
  - now always resolves to local mode,
  - lazily imports `MegaCodeLocal` to avoid import cycles.

- `mega_code/client/api/protocol.py`
  - shared client protocol including `wisdom_curate()` and `wisdom_feedback()`,
  - data models: `OperatorPlanItem`, `WisdomResultItem`, `WisdomCurateResult`,
    `WisdomFeedbackResult`, `ReliabilityMetrics`, `CausalStepFeedbackItem`,
    `SkillRefItem`.

- `mega_code/client/cli.py`
  - treats local mode as canonical,
  - no longer gates pipeline or curation commands on `MegaCodeRemote`.

- `mega_code/client/check_auth.py`
  - validates local provider setup instead of `MEGA_CODE_API_KEY`.

- `mega_code/client/skill_installer.py`
  - can install from local source paths when `SkillRefItem.url` is empty.

- `mega_code/client/run_pipeline.py`
  - wording and mode semantics now describe a local worker, not a server.

- `mega_code/client/compaction.py`
  - code block compaction for token reduction using regex-based placeholder
    replacement,
  - pure module with zero pipeline dependencies.

- `mega_code/client/curation_store.py`
  - file-based curation lifecycle persistence,
  - tracks curations through `pending` -> `running` -> `completed` status
    transitions using directory-based organization.

- `mega_code/client/host_llm.py`
  - host-agent LLM abstraction for skill evaluation,
  - detects available coding agent CLI (Claude Code, Codex, etc.) and runs
    isolated completions via subprocess,
  - no external API keys required; uses the agent's own model.

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

- `curations/{status}/`
  - file-based curation lifecycle persistence (`pending`, `running`, `completed`).

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
- `content_digest`
- `validation_level`
- `trust_tier`
- `safety_gate_status`
- `safety_gate_reason`
- `last_validated_at`
- `provenance_json`
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
- `content_digest`
- `validation_level`
- `trust_tier`
- `safety_gate_status`
- `safety_gate_reason`
- `last_validated_at`
- `provenance_json`
- `created_at`
- `embedding_json`
- `lexical_text`

This table remains the atomic validated-knowledge store, but the current local
curation path primarily retrieves through the operator graph and uses PCR
fragments as provenance-rich memory units.

#### `operators`

Purpose:
- store executable step-level knowledge units for local curation.

Fields:
- `operator_id`
- `artifact_id`
- `run_id`
- `project_id`
- `session_id`
- `name`
- `title`
- `procedure`
- `context`
- `outcome`
- `source_artifact`
- `normalized_intent`
- `slot_signature`
- `feedback_score`
- `content_digest`
- `validation_level`
- `trust_tier`
- `safety_gate_status`
- `safety_gate_reason`
- `last_validated_at`
- `provenance_json`
- `created_at`

#### `operator_procedure_index`, `operator_context_index`, `operator_outcome_index`

Purpose:
- facet-level indexes for hybrid semantic + lexical retrieval.

Fields (identical across all three):
- `operator_id`
- `facet_text`
- `embedding_json`
- `lexical_text`

Each facet index stores the text, its embedding vector, and a tokenized lexical
form used for BM25-style scoring during retrieval.

#### `operator_edges`

Purpose:
- directed graph edges between operators.

Fields:
- `edge_id`
- `source_operator_id`
- `target_operator_id`
- `edge_type` (`depends_on`, `requires_context`, `supersedes`, `conflicts_with`)
- `metadata_json`
- `created_at`

#### `operator_preconditions`

Purpose:
- environment or tooling requirements that must hold before an operator can run.

Fields:
- `precondition_id`
- `operator_id`
- `precondition_type` (`tool`, `file`, `env_var`, `package_manager`)
- `key_name`
- `value`
- `description`
- `created_at`

#### `operator_postconditions`

Purpose:
- expected outcomes or artifacts produced by an operator.

Fields:
- `postcondition_id`
- `operator_id`
- `postcondition_type` (`evidence`, `verification`, `artifact`)
- `key_name`
- `value`
- `description`
- `created_at`

#### `operator_slots`

Purpose:
- parameterizable bindings (file paths, env vars, branches) captured from the
  source session.

Fields:
- `slot_id`
- `operator_id`
- `slot_name`
- `slot_type` (`path`, `env_var`, `branch`)
- `slot_value`
- `required`
- `description`
- `created_at`

#### `operator_env_fingerprints`

Purpose:
- captured environment context at distillation time for environment-match scoring.

Fields:
- `operator_id`
- `fingerprint_json`
- `lexical_text`
- `fingerprint_hash`

The fingerprint includes:
- `project_path`, `language`, `frameworks`, `package_manager`, `branch`, `model`,
  `required_tools`, `env_var_presence`.

#### `operator_reliability`

Purpose:
- empirical reliability aggregates derived from causal feedback events.

Fields:
- `operator_id`
- `selection_count`
- `helped_count`
- `hurt_count`
- `unused_count`
- `retrieval_miss_count`
- `execution_miss_count`
- `abstain_count`
- `predicted_success_sum`
- `confidence_sum`
- `calibration_error_sum`
- `brier_score_sum`
- `outcome_count`
- `last_feedback_at`

These counters are used to derive:
- `prior_success` (evidence-based prior probability of helping),
- `confidence` (based on evidence volume and calibration),
- `retrieval_precision` (helpful rate among retrieved instances),
- `execution_success_rate` (success rate when executed),
- `calibration_error` (mean abs error of predicted vs observed),
- `brier_score` (mean squared error of predicted vs observed),
- `empirical_reliability` (evidence-weighted trust score),
- `abstain_probability` (probability the system should abstain).

#### `curation_sessions`

Purpose:
- persist generated curations for later resume and feedback linkage.

Fields:
- `session_id`
- `query`
- `curation`
- `skills_json`
- `wisdoms_json`
- `operator_plan_json`
- `confidence`
- `should_abstain`
- `abstain_reason`
- `token_count`
- `cost_usd`
- `created_at`
- `status`

#### `curation_feedback`

Purpose:
- persist feedback linked to a curation session.

Fields:
- `feedback_id`
- `session_id`
- `feedback_text`
- `failure_stage` (`none`, `retrieval`, `execution`, `mixed`, `unknown`)
- `should_abstain`
- `summary_json`
- `created_at`

#### `curation_feedback_steps`

Purpose:
- persist per-step causal feedback for individual operators in a curation.

Fields:
- `step_feedback_id`
- `feedback_id`
- `session_id`
- `operator_id`
- `operator_title`
- `verdict` (`helped`, `hurt`, `unused`, `missing`)
- `failure_stage`
- `selected`
- `predicted_success`
- `predicted_confidence`
- `note`
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
it can stop gracefully between clusters.

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

The current OSS distillation logic uses a clustered closed-loop pipeline that
combines heuristic trace extraction with structured LLM analysis passes. The
pipeline operates at the cluster level rather than the individual session level.

### 10.1 Trace extraction

`_build_session_trace()` converts each `TurnSet` into a `SessionTrace` containing:

- `keywords`: frequency-ranked tokens from commands, tool names, and content,
- `dominant_tools`: most common tool/command names,
- `referenced_paths`: file paths extracted from step commands and evidence,
- `referenced_env_vars`: environment variable names extracted from step text,
- `env_fingerprint`: project-level environment context derived from manifest
  files (package.json, pyproject.toml, go.mod, Cargo.toml, Gemfile),
- `descriptor_text`: combined text of first user prompt, keywords, tools, paths,
  and step labels,
- `descriptor_embedding`: vector embedding of the descriptor text,
- `steps`: all steps extracted from turns (commands, tool calls, analysis),
- `success_steps`: non-error steps,
- `error_windows`: each error step with its previous step and up to 3 recovery
  steps,
- `correction_windows`: error steps that have recovery steps following them.

### 10.2 Environment fingerprinting

`_inspect_project_fingerprint()` reads project manifest files to detect:

| Manifest | Language | Frameworks | Package Manager |
|----------|----------|------------|-----------------|
| `package.json` | JS/TS | next, react, vite, express, nestjs, astro, svelte | pnpm, yarn, bun, npm |
| `pyproject.toml` | Python | fastapi, django, flask, sqlalchemy, pytest, celery | uv, poetry, pip |
| `go.mod` | Go | gin, gorm, cobra | go |
| `Cargo.toml` | Rust | axum, tokio, sqlx, actix | cargo |
| `Gemfile` | Ruby | rails, sinatra, sidekiq | bundler |

The fingerprint also records: branch, model, required tools, and env var presence.

### 10.3 Session clustering

`_cluster_traces()` groups traces into `TraceCluster` objects:

- **Similarity metric**: weighted combination of:
  - 0.6 × cosine similarity of descriptor embeddings,
  - 0.25 × Jaccard similarity of dominant tools,
  - 0.15 × Jaccard similarity of referenced paths.
- **Hard constraints**: traces with different languages or package managers
  cannot cluster (`_cluster_pair_allowed`).
- **Connected components**: traces above a similarity threshold (0.72, or 0.68
  for anchor neighbors) are connected; connected components form clusters.
- **Anchor mode**: when a `session_id` is specified, only the cluster containing
  that session is emitted, with neighbors capped at 4.

### 10.4 Success seed extraction

`_success_seed_candidates()` extracts workflow step candidates from each trace's
success steps, classified by target:

- `canonical_workflow`: normal workflow steps,
- `verification_loop`: test/lint/check/build steps.

Candidates are bucketed by (target, title), aggregating evidence session IDs and
support counts across cluster members.

### 10.5 Error seed extraction

`_error_seed_candidates()` extracts candidates from error and correction windows:

- `correction_patterns`: how recovery proceeds after failure,
- `when_to_retry`: conditions under which retrying is appropriate,
- `failure_guards`: steps that should not be continued past on failure,
- `when_to_stop`: signals to stop retrying without new evidence.

### 10.6 Analyst LLM passes

Two structured LLM passes analyze each cluster:

- **Success Analyst** (`_run_analyst_pass` with `SUCCESS_ANALYST` marker):
  reviews success candidates and returns JSON proposals.
- **Error Analyst** (`_run_analyst_pass` with `ERROR_ANALYST` marker):
  reviews error candidates and returns JSON proposals.

Both passes receive the cluster ID, member session IDs, keywords, and
stripped candidates. They return `_AnalystPass` objects containing typed
`_AnalystProposal` entries.

Proposals are matched back to the original candidates by normalized lookup keys
to preserve representative step metadata (kind, command, tool_name, tool_target).

### 10.7 Proposal grouping

`_group_proposals()` deduplicates the combined analyst proposals:

- proposals are embedded,
- ranked by support count,
- grouped when they share the same target and either:
  - have the same normalized title, or
  - have cosine similarity >= 0.84.

Each group keeps the highest-support representative and merges evidence session
IDs and examples.

### 10.8 Consolidator LLM pass

`_run_consolidator_pass()` takes the grouped proposals and produces a
`_ConsolidatedCluster` containing:

- `summary`: short cluster description,
- `applicability`: when to use this workflow,
- `canonical_workflow`: ordered `_WorkflowItem` list with titles, rules,
  evidence, and support counts,
- `verification_loop`: verification steps,
- `failure_guards`: failure guardrails,
- `strategy`: `_StrategySections` with delta rules, correction patterns,
  when to retry, when to stop, and support signals,
- `memory_fragments`: `_MemoryFragment` list for PCR persistence,
- `keywords`: cluster-level keywords.

When the consolidator returns empty sections, the runtime fills them from
grouped proposals as a deterministic fallback.

### 10.9 Skill rendering

`_build_cluster_skill_markdown()` constructs:

- frontmatter with cluster metadata,
- summary from the consolidator,
- applicability rules,
- canonical workflow with per-step rules, support counts, and examples,
- verification loop,
- failure guards,
- cluster evidence (sessions, dominant tools, error rate, correction count).

### 10.10 Strategy rendering

`_build_cluster_strategy_markdown()` constructs:

- delta rules,
- correction patterns,
- when-to-retry rules,
- when-to-stop rules,
- support signals,
- cluster evidence summary.

### 10.11 Governance payload construction

`_build_governance_payload()` constructs a governance record for each distilled
artifact:

- `content_digest`: SHA-256 of the rendered content,
- `validation_level`: `observed` (no tests), `verified` (has test artifacts),
  or `reproduced` (support >= 2 and has test artifacts),
- `trust_tier`: `provisional` (observed), `trusted` (verified/reproduced),
  or `hardened` (reproduced with corrections),
- `safety_gate_status`: `approved`, `review_required`, or `blocked`,
- `safety_gate_reason`: human-readable explanation,
- `provenance`:
  - `source_sessions`: deduplicated session IDs,
  - `source_paths`: referenced file paths,
  - `evidence_digest`: SHA-256 of the provenance chain,
  - `test_artifacts`: verification steps extracted from success steps
    (`_verification_artifacts_from_steps`),
  - `test_artifact_digest`: SHA-256 of the test artifacts,
  - `revalidation_triggers`: conditions that should trigger re-evaluation
    (source artifact digest changed, package manager changed, framework
    stack changed, etc.),
  - `rollback_lineage`: error/recovery pairs from correction windows,
  - `support_count`, `correction_count`, `error_rate`.

Operators and PCR fragments receive cloned governance payloads with additional
provenance fields (`source_artifact_digest`, `operator_index`, `step_kind`,
`step_paths`, `fragment_kind`, `fragment_sessions`).

### 10.12 PCR fragment creation

Each consolidated memory fragment becomes a PCR fragment with:

- `procedure`: the fragment's procedure text,
- `context`: the fragment's context text,
- `resultant`: the fragment's resultant text,
- `constraints`: the fragment's constraint text,
- `evidence_refs`: session IDs from the consolidator,
- `source_artifact`: parent skill name,
- `dependency_ids`: empty (fragments are independent),
- `embedding`: provider-generated vector,
- `lexical_text`: concatenated searchable text,
- governance fields cloned from the parent artifact.

### 10.13 Operator synthesis

`_operator_payloads()` creates operators from the consolidated canonical workflow:

Each operator receives:

- `procedure`: normalized step procedure text,
- `context`: project/language/framework context text,
- `outcome`: expected outcome or recovery text,
- `normalized_intent`: tokenized step label (first 8 tokens),
- `slot_signature`: hash of the operator's parameterizable slots,
- three facet indexes (procedure, context, outcome), each with:
  - `facet_text`, `embedding`, `lexical_text`,
- `edges`:
  - `depends_on` to previous operator (preserve step order),
  - `requires_context` to last analysis operator (context establishment),
- `preconditions`: derived from step commands/labels/evidence:
  - tool availability, file existence, env var presence, package manager,
- `postconditions`: expected evidence snippets, verification commands, artifact
  paths,
- `slots`: parameterizable bindings (paths, env vars, branches),
- `env_fingerprint`: cluster-level environment context with hash,
- governance fields cloned from the parent artifact.

### 10.14 Single-session fallback

`distill_session()` provides a simpler non-clustered path for individual sessions.
It follows the same governance, operator, and PCR creation patterns but without
the clustering, analyst, and consolidator passes.

## 11. Artifact Persistence

After distillation, the runtime writes both:

- pending outputs for normal MEGA-Code review flow,
- normalized artifacts, PCR fragments, and operators into SQLite.

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

Pending skills now carry the same governance summary exposed in SQLite:

- whether validation passed,
- validation level,
- trust tier,
- safety gate status and reason.

This preserves the review/install UX already used elsewhere in the repo while
making "validated knowledge" a runtime-visible state rather than only a docs
claim.

## 12. Local Curation and Retrieval

### 12.1 Entry point

`MegaCodeLocal.wisdom_curate()` delegates to `runtime.curate_local_wisdom()`.

### 12.2 Candidate corpus

Candidates are loaded from `operators`, joined with their parent artifacts.

Each operator carries:

- three facet indexes:
  - procedure,
  - context,
  - outcome,
- an environment fingerprint,
- dependency/context/conflict edges,
- empirical reliability metrics,
- governance metadata:
  - validation level,
  - trust tier,
  - safety gate status,
  - provenance and revalidation triggers.

### 12.3 Dynamic governance gate

Before ranking, the runtime applies `_evaluate_operator_governance()`:

- superseded operators are removed first,
- `observed` knowledge defaults to `review_required`,
- source-artifact digest drift can downgrade an otherwise approved operator,
- package-manager or language drift can trigger revalidation,
- repeated harmful or abstention feedback can hard-block reuse.

Only operators that pass this safety gate are eligible to influence future
curations. The governance gate counts (approved, review_required, blocked) are
surfaced in the curation output.

### 12.4 Facet scoring

Each eligible operator is scored independently across four dimensions:

1. **Procedure facet**: 0.65 × semantic + 0.35 × BM25 lexical,
2. **Context facet**: same weights,
3. **Outcome facet**: same weights,
4. **Contextual lexical**: BM25 over a combined text including operator title,
   source artifact, intent, all facet lexical texts, fingerprint text, and
   dependency titles.

### 12.5 Seed selection via RRF

The top-ranked operators from each of the four scoring dimensions are fused
using reciprocal-rank fusion (RRF, rank constant = 60). Seeds are the top
min(top_k, 6) operators from the fused ranking.

### 12.6 Structural expansion via PageRank

`_personalized_pagerank()` diffuses seed scores through the operator graph:

- damping factor (alpha) = 0.82,
- 15 iterations,
- edges traversed: `depends_on`, `requires_context`.

Operators with structural scores above a floor threshold (max(0.08, peak × 0.3))
are added as frontier nodes. The full dependency closure is expanded to ensure
all prerequisites are included.

### 12.7 Reranking

The expanded set is reranked with weighted signals:

| Signal | Weight |
|--------|--------|
| Seed score (RRF) | 0.34 |
| Structural score (PageRank) | 0.24 |
| Best facet score | 0.14 |
| Contextual score | 0.08 |
| Environment match score | 0.14 |
| Structural support score | 0.06 |
| Recency boost | additive (max 0.08) |
| Provenance boost | additive (0.04 if source path exists) |
| Reliability boost | additive (from empirical metrics) |
| Dependency penalty | subtractive (0.02 × excess deps) |

### 12.8 Conflict suppression

After reranking, operators are selected in score order. When an operator is
selected, any operators in its `conflicts_with` set are dropped.

### 12.9 Topological wave planning

`_topological_waves()` arranges the selected operators into execution waves:

- earlier waves establish required context or prerequisites,
- later waves carry dependent execution steps,
- operators in the same wave may be marked `parallelizable`,
- missing preconditions or slots change readiness status to `blocked`.

### 12.10 Prediction metrics

For each operator, `_current_prediction_metrics()` computes:

- `predicted_success`: estimated probability of helping on the current task,
- `confidence`: confidence in the prediction based on evidence volume and
  calibration,
- `abstain_probability`: probability the system should abstain,
- `should_abstain`: boolean flag,
- `reliability_boost`: additive boost from empirical reliability.

### 12.11 Curation-level abstention

The system abstains from the entire curation when:

- no operators survive retrieval and conflict filtering,
- all top candidates have `should_abstain=True`,
- best confidence < 0.45,
- best predicted success < 0.42.

### 12.12 Cheatmap generation

The curation document contains:

- problem statement,
- workflow heading,
- overview of the retrieval method,
- governance summary (approved / review-required / blocked counts),
- readiness summary (ready / blocked counts),
- seed count and bundle size,
- reliability summary (confidence, best predicted success, abstain flag),
- seed matches with scores,
- ordered execution waves with per-step:
  - title, source artifact, score,
  - inclusion reason,
  - compact context package,
  - dependency/context requirements,
  - readiness blockers,
  - predicted success, confidence,
  - validation level, trust tier, safety gate status,
  - abstention reason when applicable,
  - reliability metrics when available.

### 12.13 Skill references

`SkillRefItem` is used in local mode with:

- `name`
- `path`
  - local source path for the rendered skill,
- `url=""`

The installer now interprets this correctly and copies from local source.

## 13. Feedback Loop

### 13.1 Feedback persistence

`save_feedback()` in `LocalStore`:

1. infers failure stage and should-abstain from feedback text when not explicitly
   provided,
2. resolves per-step feedback via `resolve_step_feedback()`:
   - explicit step feedback is used directly,
   - unstructured legacy feedback falls back to the top-ranked operator when
     there is a clear positive or negative signal,
3. writes a `curation_feedback` row,
4. for each resolved step:
   - writes a `curation_feedback_steps` row with verdict, failure stage,
     predicted success/confidence snapshot,
   - calls `_apply_operator_feedback_event()` to update reliability,
5. updates the associated `curation_sessions` row to `completed`.

### 13.2 Operator reliability aggregation

`_apply_operator_feedback_event()` updates `operator_reliability`:

- increments `selection_count` (when selected),
- increments `helped_count`, `hurt_count`, `unused_count` (by verdict),
- increments `retrieval_miss_count` (when failure_stage is `retrieval` or
  `mixed`),
- increments `execution_miss_count` (when failure_stage is `execution` or
  `mixed`),
- increments `abstain_count` (when should_abstain is true),
- updates `predicted_success_sum`, `confidence_sum` from the plan snapshot,
- computes and accumulates `calibration_error_sum` (|predicted - observed|),
- computes and accumulates `brier_score_sum` ((predicted - observed)^2),
- increments `outcome_count`.

### 13.3 Derived reliability metrics

`_summarize_operator_reliability()` derives:

- `prior_success`: helped / max(selection, 1),
- `confidence`: based on evidence volume with calibration error penalty,
- `retrieval_precision`: (selection - retrieval_miss) / max(selection, 1),
- `execution_success_rate`: (helped) / max(selection - unused, 1),
- `calibration_error`: mean absolute error,
- `brier_score`: mean squared error,
- `empirical_reliability`: evidence-weighted trust score,
- `abstain_probability`: derived from abstain count and hurt/selection ratio.

### 13.4 Safety-gated reuse

In the current runtime, "validated knowledge" specifically means knowledge that
has survived both:

- static governance recorded at distillation time,
- dynamic governance checks at retrieval time.

That dynamic check consults:

- validation level,
- trust tier,
- source-artifact digest drift,
- environment drift,
- abstention history,
- repeated harmful feedback.

This is what prevents a merely observed or stale skill from automatically
influencing later sessions.

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

### 16.1 Test suite

| Test File | Coverage |
|-----------|----------|
| `test_local_runtime.py` | Full lifecycle: ingest, pipeline, curation, feedback, stop, install |
| `test_local_setup.py` | Provider key validation |
| `test_pipeline_constraints.py` | Pipeline configuration constraints |
| `test_shared_env.py` | Shared environment variable handling |
| `test_operator_graph.py` | Operator graph: facet retrieval, governance gating, PageRank expansion, wave planning, causal step feedback, reliability aggregation, environment-match scoring |
| `test_runtime_cli_integration.py` | End-to-end CLI subprocess tests: pipeline trigger, curate, install, feedback, reranking across process boundaries |
| `test_hook_contracts.py` | Hook execution paths and deterministic plugin contracts |
| `test_skill_wrappers.py` | Skill enhancement and wrapping |
| `test_plugin_contracts.py` | Plugin integration contracts |

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

- distillation uses heuristic clustering and structured LLM passes, not learned
  models,
- PCR generation is consolidator-derived rather than fully model-generated,
- validation and trust policy are heuristic and local-only,
- feedback weighting is heuristic,
- dependency graphs are shallow and mostly sequential,
- retrieval is exact and SQLite-backed, not ANN-backed,
- generation is only lightly used in the current local pipeline (analyst and
  consolidator passes).

These are acceptable for the current OSS objective because the implementation
already provides:

- a real local runtime,
- clustered distillation with LLM analysis,
- async runs,
- durable state,
- a safety-gated operator graph with facet indexes,
- retrievable PCR fragments,
- hybrid retrieval with RRF and PageRank,
- topological wave planning,
- local cheatmap generation with abstention support,
- a causal feedback loop with operator reliability tracking.

## 18. Recommended Extension Points

If the local runtime is extended later, the most natural places are:

### Better distillation

File:
- `mega_code/pipeline/runtime.py`

Possible improvements:
- richer clustering with learned similarity models,
- multi-round analyst passes with chain-of-thought,
- better fallback handling when LLM returns invalid JSON,
- cross-cluster deduplication of overlapping workflows.

### Better retrieval

Files:
- `mega_code/pipeline/runtime.py`
- `mega_code/pipeline/store.py`

Possible improvements:
- ANN indexing for large operator sets,
- learned reranking models,
- richer edge types (e.g., `enhances`, `specializes`),
- stronger enterprise policy hooks for trust tiers, signatures, and review
  approvals.

### Better feedback

File:
- `mega_code/pipeline/store.py`

Possible improvements:
- decay old feedback over time,
- store richer external test artifacts and signed provenance bundles,
- cross-session feedback correlation,
- A/B evaluation of retrieval quality.

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
- **traces extracted and clustered**
- **analyst passes refine candidates**
- **consolidator produces canonical workflows**
- **artifacts, PCR, and operators stored locally with governance**
- **curation retrieves from a safety-gated operator graph via RRF + PageRank**
- **topological wave planning produces execution-ready operator plans**
- **causal feedback updates operator reliability**
- **reliability informs future retrieval, prediction, and abstention**

That is the core architecture of the current local runtime.
