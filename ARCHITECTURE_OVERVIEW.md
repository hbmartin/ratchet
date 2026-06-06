# Ratchet Architecture

This document describes the architecture of Ratchet, an open-source Claude Code
plugin that collects interaction data, extracts reusable skills and strategies,
and optimizes AI workflows through a local-first runtime.

## 1. System Overview

Ratchet operates as a local-first runtime. The Ratchet service is not required for
normal pipeline or curation flows. User-controlled provider keys (`GEMINI_API_KEY`,
`OPENAI_API_KEY`) power embeddings and optional generation.

```mermaid
graph TB
    subgraph "Claude Code"
        CC[Claude Code IDE]
        Hooks[Hooks Engine]
    end

    subgraph "Ratchet Plugin"
        Collector[Collector]
        CLI[CLI - ratchet]
        RunPipeline[Pipeline Runner]
        CheckPending[Pending Checker]
    end

    subgraph "Local Runtime"
        LocalClient[RatchetLocal]
        Worker[Detached Worker]
        Runtime[Runtime Engine]
        Store[LocalStore - SQLite]
        LLM[LLM Provider Layer]
    end

    subgraph "External Providers"
        Gemini[Gemini API]
        OpenAI[OpenAI API]
    end

    subgraph "Storage"
        SQLite[(local-runtime.sqlite3)]
        FS[File System]
    end

    CC --> Hooks
    Hooks -->|SessionStart/End| Collector
    Hooks -->|UserPromptSubmit| Collector
    Hooks -->|UserPromptSubmit| CheckPending
    Hooks -->|Stop| Collector

    CLI --> LocalClient
    RunPipeline --> LocalClient
    Collector --> LocalClient

    LocalClient --> Store
    LocalClient -->|spawns| Worker
    Worker --> Runtime
    Runtime --> Store
    Runtime --> LLM

    LLM --> Gemini
    LLM --> OpenAI

    Store --> SQLite
    Store --> FS
```

## 2. Package Structure

The codebase is organized into two main packages:

```
ratchet/
├── client/              # User-facing CLI, hooks, data collection
│   ├── api/             # Client factory, protocol, remote/sync adapters
│   ├── filters/         # Content filtering (paths, secrets)
│   ├── history/         # Multi-source session loading
│   │   └── sources/     # Claude, Codex, Gemini, Cursor, Parquet, etc.
│   ├── compaction.py    # Code block compaction for token reduction
│   ├── curation_store.py # File-based curation lifecycle persistence
│   ├── host_llm.py      # Host-agent LLM abstraction (subprocess-based)
│   └── utils/           # I/O, path, env, tracing helpers
├── pipeline/            # Local runtime engine
│   ├── local_client.py  # RatchetLocal implementation
│   ├── runtime.py       # Distillation, retrieval, curation logic
│   ├── store.py         # SQLite state store
│   ├── llm.py           # Provider abstraction (Gemini, OpenAI, Fake)
│   └── worker.py        # Detached pipeline worker entrypoint
hooks/                   # Claude Code hook definitions (hooks.json)
scripts/                 # Session startup scripts
skills/                  # Installed skill files
tests/                   # Test suite
```

## 3. Data Flow: Collection to Curation

The system operates as five connected loops:

```mermaid
flowchart LR
    A[1. Collection] --> B[2. Extraction]
    B --> C[3. Persistence]
    C --> D[4. Retrieval & Curation]
    D --> E[5. Feedback]
    E -->|updates operator reliability| D

    style A fill:#e1f5fe
    style B fill:#fff3e0
    style C fill:#e8f5e9
    style D fill:#f3e5f5
    style E fill:#fce4ec
```

1. **Collection** -- Session data is normalized into `TurnSet` objects and persisted
   locally via `upload_trajectory()`.
2. **Extraction** -- `trigger_pipeline_run()` spawns a detached worker that runs the
   clustered closed-loop distiller: trace extraction, project/anchor clustering,
   success/error analyst JSON passes, deterministic proposal consolidation,
   cluster-level skill/strategy generation, operator synthesis, and PCR fragment
   persistence.
3. **Persistence** -- Rendered artifacts are written to the file system for human
   review; normalized state (artifacts, operators, PCR fragments, governance metadata)
   is written to SQLite.
4. **Retrieval & Curation** -- `wisdom_curate()` runs hybrid seed retrieval across
   procedure/context/outcome facets plus contextual lexical matching, fuses seeds with
   reciprocal-rank fusion (RRF), expands through operator edges using personalized
   PageRank, reranks with structural/env/feedback signals, and emits topologically
   ordered execution waves with compact per-step context packages.
5. **Feedback** -- `wisdom_feedback()` stores per-step causal feedback, writes
   per-step feedback events, and aggregates operator reliability/calibration metrics.
   `feedback_score` is derived from empirical evidence rather than free-text polarity.

## 4. Hook Integration

Ratchet integrates with Claude Code through its hooks system. Four hook events
drive data collection and skill delivery:

```mermaid
sequenceDiagram
    participant CC as Claude Code
    participant SS as session-start.sh
    participant Col as collector.py
    participant CP as check_pending.py
    participant Store as LocalStore

    CC->>SS: SessionStart
    SS-->>CC: Write plugin-root breadcrumb

    CC->>Col: UserPromptSubmit (stdin: prompt data)
    Col->>Store: Persist turn data
    CC->>CP: UserPromptSubmit
    CP-->>CC: Inject pending skills (if any)

    CC->>Col: Stop (stdin: transcript)
    Col->>Store: Append turns, update stats

    CC->>Col: SessionEnd
    Col->>Store: Finalize session metadata
```

## 5. Client Architecture

### 5.1 Protocol and Factory

All client operations go through `RatchetBaseClient`, a Python `Protocol` class.
The factory always resolves to local mode:

```mermaid
classDiagram
    class RatchetBaseClient {
        <<Protocol>>
        +upload_trajectory()
        +trigger_pipeline_run()
        +get_pipeline_status()
        +get_outputs()
        +stop_pipeline()
        +wisdom_curate()
        +wisdom_feedback()
        +save_profile()
        +load_profile()
        +enhance_skill()
        +get_active_pipelines()
    }

    class RatchetLocal {
        -store: LocalStore
        -backend: str
        -project_id: str
        -model_name: str
    }

    class RatchetRemote {
        -server_url: str
        -api_key: str
        +HTTP-based implementation
    }

    RatchetBaseClient <|.. RatchetLocal : implements
    RatchetBaseClient <|.. RatchetRemote : implements (legacy)

    class create_client {
        <<factory>>
        +always returns RatchetLocal
    }
    create_client ..> RatchetLocal : creates
```

`create_client()` lazy-imports `RatchetLocal` inside the function body to avoid
import cycles (`profile -> api -> local_client -> profile`).

### 5.2 History Loading

The history system uses a pluggable `DataSource` protocol to load sessions from
multiple AI coding tools:

| Source | Module | Description |
|--------|--------|-------------|
| Claude Native | `sources/claude_native.py` | Claude Code JSONL sessions |
| Ratchet | `sources/ratchet.py` | Plugin-collected sessions |
| Codex | `sources/codex.py` | OpenAI Codex CLI |
| Cursor | `sources/cursor.py` | Cursor IDE sessions |
| Gemini | `sources/gemini.py` | Gemini CLI sessions |
| OpenCode | `sources/opencode.py` | OpenCode sessions |
| Parquet | `sources/parquet.py` | Dataset files (benchmarks) |

`DataLoader` aggregates sources and provides unified iteration via `iter_all()`.

## 6. Pipeline Run Lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: trigger_pipeline_run()
    queued --> running: worker starts
    running --> completed: distillation finishes
    running --> failed: exception / worker dies
    running --> stopped: user requests stop
    queued --> failed: worker never starts

    completed --> [*]
    failed --> [*]
    stopped --> [*]

    note right of running
        Worker checks is_stop_requested()
        between sessions for graceful stop.
        PID-based liveness reconciliation
        catches unexpected worker death.
    end note
```

### 6.1 Triggering

`RatchetLocal.trigger_pipeline_run()`:
1. Checks for an active run on the same `project_id`.
2. If active and `force=False`: raises HTTP 409 for existing conflict handling.
3. If `force=True`: stops the existing run first.
4. Creates a `pipeline_runs` row with `status='queued'`.
5. Creates `~/.local/ratchet/runs/{project_id}/{run_id}/`.
6. Redirects worker stdout/stderr to `worker.log`.
7. Spawns a detached worker: `python -m ratchet.pipeline.worker --run-id <id>`.
8. Records the worker PID.

### 6.2 Worker Execution

The worker (`ratchet/pipeline/worker.py`) is intentionally minimal:
1. Marks run as started and stores PID.
2. Calls `run_local_pipeline(run_id)`.
3. Writes lifecycle events and worker log lines.
4. Writes terminal state (`completed`, `failed`, or `stopped`).

### 6.3 Status Reconciliation

`LocalStore.get_pipeline_status()` calls `_reconcile_row()` to handle workers that
disappear without writing terminal state. If a run is `queued` or `running` but its
PID is no longer alive, the row is rewritten to `failed`.

### 6.4 Traceability

Each run stores:

- `worker.log` for redirected worker stdout/stderr
- `events.jsonl` plus matching `pipeline_events` rows
- `llm/` prompt and response artifacts plus `pipeline_llm_calls` rows
- heartbeat fields on `pipeline_runs`

Debugging starts with:

```bash
ratchet debug
ratchet debug --run-id <RUN_ID>
ratchet debug-bundle --run-id <RUN_ID>
```

## 7. Clustered Distillation Pipeline

The distiller converts raw session data into retrievable knowledge through a
multi-stage clustering and analysis pipeline:

```mermaid
flowchart TD
    Sessions[Session TurnSets] --> Traces[Build Session Traces]
    Traces --> Embed[Embed Descriptor Texts]
    Embed --> Cluster[Cluster by Similarity]

    subgraph "Per Cluster"
        Cluster --> SuccessSeeds[Extract Success Seed Candidates]
        Cluster --> ErrorSeeds[Extract Error Seed Candidates]
        SuccessSeeds --> SuccessAnalyst[LLM Success Analyst Pass]
        ErrorSeeds --> ErrorAnalyst[LLM Error Analyst Pass]
        SuccessAnalyst --> Group[Group & Deduplicate Proposals]
        ErrorAnalyst --> Group
        Group --> Consolidator[LLM Consolidator Pass]
        Consolidator --> SkillMD[Build Cluster Skill Markdown]
        Consolidator --> StrategyMD[Build Cluster Strategy Markdown]
        Consolidator --> Operators[Synthesize Operators]
        Consolidator --> PCR[Build PCR Fragments]
    end

    SkillMD --> ArtifactDB[(artifacts table)]
    StrategyMD --> ArtifactDB
    PCR --> PCRDB[(pcr_fragments table)]
    Operators --> OpDB[(operators + indexes)]

    SkillMD --> PendingFS[pending-skills/]
    StrategyMD --> PendingFS2[pending-strategies/]
    SkillMD --> KnowledgeFS[knowledge/skills/]
    StrategyMD --> KnowledgeFS2[knowledge/strategies/]
```

### 7.1 Trace Extraction

Each session is converted into a `SessionTrace` containing:
- Keyword frequency analysis
- Dominant tool identification
- Referenced paths and environment variables
- Environment fingerprint (language, frameworks, package manager, branch)
- Success steps, error windows, and correction windows
- Descriptor text and embedding for clustering

### 7.2 Session Clustering

Traces are clustered via connected components with similarity thresholds:
- **Similarity metric**: 0.6 × cosine(descriptor embeddings) + 0.25 × Jaccard(tools) + 0.15 × Jaccard(paths)
- **Hard constraints**: sessions with different languages or package managers cannot cluster
- **Anchor mode**: when a `session_id` is specified, only the cluster containing that session is emitted

### 7.3 Analyst Passes

Two structured LLM passes analyze each cluster:
- **Success Analyst** -- reviews successful workflow steps, bucketed by target
  (`canonical_workflow` or `verification_loop`)
- **Error Analyst** -- reviews correction patterns, failure guards, retry/stop signals

Both passes return JSON proposals that are then grouped by semantic similarity
(cosine >= 0.84) and deduplicated by support count.

### 7.4 Consolidator Pass

A final LLM pass produces a `_ConsolidatedCluster` containing:
- Summary and applicability rules
- Canonical workflow steps with evidence and support counts
- Verification loop, failure guards
- Strategy sections (delta rules, correction patterns, retry/stop signals)
- Memory fragments for PCR persistence

### 7.5 Governance

Every distilled artifact (skill, strategy, PCR fragment, operator) receives a
governance record:

| Field | Values | Purpose |
|-------|--------|---------|
| `validation_level` | `observed`, `verified`, `reproduced` | Maturity of evidence |
| `trust_tier` | `provisional`, `trusted`, `hardened` | Derived trust level |
| `safety_gate_status` | `approved`, `review_required`, `blocked` | Reuse eligibility |
| `safety_gate_reason` | Free text | Why the gate resolved that way |
| `content_digest` | SHA-256 | Drift detection |
| `provenance_json` | JSON object | Source sessions, test artifacts, rollback lineage, revalidation triggers |

## 8. Operator Graph

Operators are the primary retrieval and execution-planning units. Each operator
represents a step-level knowledge unit with rich structural metadata:

```mermaid
erDiagram
    operators {
        text operator_id PK
        text title
        text procedure
        text context
        text outcome
        text normalized_intent
        text slot_signature
        real feedback_score
        text validation_level
        text trust_tier
        text safety_gate_status
        text provenance_json
    }

    operator_procedure_index {
        text operator_id PK
        text facet_text
        text embedding_json
        text lexical_text
    }

    operator_context_index {
        text operator_id PK
        text facet_text
        text embedding_json
        text lexical_text
    }

    operator_outcome_index {
        text operator_id PK
        text facet_text
        text embedding_json
        text lexical_text
    }

    operator_edges {
        text source_operator_id
        text target_operator_id
        text edge_type
    }

    operator_preconditions {
        text operator_id
        text precondition_type
        text key_name
        text value
    }

    operator_postconditions {
        text operator_id
        text postcondition_type
        text key_name
        text value
    }

    operator_slots {
        text operator_id
        text slot_name
        text slot_type
        text slot_value
    }

    operator_env_fingerprints {
        text operator_id PK
        text fingerprint_json
        text fingerprint_hash
    }

    operator_reliability {
        text operator_id PK
        int selection_count
        int helped_count
        int hurt_count
        real calibration_error
        real brier_score
    }

    operators ||--|| operator_procedure_index : "has"
    operators ||--|| operator_context_index : "has"
    operators ||--|| operator_outcome_index : "has"
    operators ||--o{ operator_edges : "connects"
    operators ||--o{ operator_preconditions : "requires"
    operators ||--o{ operator_postconditions : "produces"
    operators ||--o{ operator_slots : "binds"
    operators ||--|| operator_env_fingerprints : "has"
    operators ||--o| operator_reliability : "tracks"
```

### Edge types
- **`depends_on`** -- sequential ordering (previous step must complete)
- **`requires_context`** -- analysis step established execution context
- **`supersedes`** -- marks an older operator as replaced
- **`conflicts_with`** -- mutual exclusion during retrieval

## 9. Retrieval and Curation

```mermaid
flowchart TD
    Query[User Query] --> EmbedQ[Embed Query]
    Query --> TokenQ[Tokenize Query]

    EmbedQ --> Proc[Score: Procedure Facet]
    EmbedQ --> Ctx[Score: Context Facet]
    EmbedQ --> Out[Score: Outcome Facet]
    TokenQ --> Lex[Score: Contextual Lexical]

    Proc --> RRF[Reciprocal Rank Fusion]
    Ctx --> RRF
    Out --> RRF
    Lex --> RRF

    RRF --> Seeds[Select Seed Nodes]
    Seeds --> PPR[Personalized PageRank]
    PPR --> Frontier[Select Frontier via Structural Score]
    Frontier --> Expand[Expand Dependency Closure]
    Expand --> Rerank[Rerank with Combined Signals]
    Rerank --> Conflict[Suppress Conflicts]
    Conflict --> Waves[Build Topological Execution Waves]
    Waves --> Plan[Emit OperatorPlanItems]

    subgraph "Reranking Weights"
        direction LR
        S1["Seed: 0.34"]
        S2["Structural: 0.24"]
        S3["Facet: 0.14"]
        S4["Contextual: 0.08"]
        S5["Env Match: 0.14"]
        S6["Support: 0.06"]
        S7["+ recency, provenance, reliability"]
    end
```

### 9.1 Governance Gate

Before ranking, operators pass a dynamic governance check:
- `observed` knowledge defaults to `review_required`
- Source-artifact digest drift can downgrade an otherwise approved operator
- Package-manager or language drift triggers revalidation
- Repeated harmful or abstention feedback can hard-block reuse

Only operators that pass the safety gate are eligible for retrieval.

### 9.2 Seed Selection

Each eligible operator is scored independently across four dimensions:
- Procedure facet (semantic + BM25 lexical)
- Context facet (semantic + BM25 lexical)
- Outcome facet (semantic + BM25 lexical)
- Contextual lexical overlap (operator-level BM25 including dependency titles)

The top-ranked operators from each dimension are fused using RRF to produce seed
nodes.

### 9.3 Structural Expansion

From seeds, personalized PageRank diffuses scores through `depends_on` and
`requires_context` edges. Operators above a structural floor threshold are added
as frontier nodes. The full dependency closure is then expanded to ensure all
prerequisites are included.

### 9.4 Topological Wave Planning

Selected operators are arranged into dependency-respecting execution waves:
- Earlier waves establish required context or prerequisites
- Later waves carry dependent execution steps
- Operators in the same wave may be marked `parallelizable`
- Missing preconditions or slots change readiness status to `blocked`

### 9.5 Abstention

The system can abstain from recommending operators when:
- No operators survive governance gating
- All top candidates have insufficient calibrated evidence
- Best predicted success is below 0.42
- Best confidence is below 0.45

## 10. LLM Provider Layer

```mermaid
classDiagram
    class BaseLocalLLM {
        +provider: str
        +default_generation_model: str
        +embed_documents(texts) list~list~float~~
        +embed_query(text) list~float~
        +generate_text(prompt, model) str
    }

    class GeminiLocalLLM {
        +provider = "gemini"
        +Uses gemini-embedding-001
        +128-dim normalized vectors
    }

    class OpenAILocalLLM {
        +provider = "openai"
        +Uses text-embedding-3-small
        +128-dim pinned vectors
    }

    class FakeLocalLLM {
        +provider = "fake"
        +Deterministic hash-based
        +No network dependency
    }

    BaseLocalLLM <|-- GeminiLocalLLM
    BaseLocalLLM <|-- OpenAILocalLLM
    BaseLocalLLM <|-- FakeLocalLLM
```

Provider selection order in `create_llm_client()`:
1. `RATCHET_TEST_FAKE_LLM=1` -- deterministic test provider
2. `GEMINI_API_KEY` -- Gemini REST provider
3. `OPENAI_API_KEY` -- OpenAI REST provider
4. Otherwise -- raises `LocalLLMError`

All providers normalize embeddings to 128 dimensions for SQLite storage compatibility.

## 11. Storage Architecture

### 11.1 Storage Layout

```
~/.local/ratchet/                 # RATCHET_DATA_DIR override
├── local-runtime.sqlite3            # Runtime state database
├── .env                             # Credential store
├── profile.json                     # User profile
├── plugin-root                      # Breadcrumb to plugin directory
├── runs/{project_id}/{run_id}/       # Worker logs, events, LLM artifacts
├── projects/{project_id}/
│   └── {session_id}/
│       ├── turns.jsonl              # Normalized turn data
│       ├── metadata.json            # Session metadata
│       └── stats.json               # Session statistics
├── knowledge/
│   ├── skills/{name}/SKILL.md       # Rendered skill sources
│   └── strategies/{name}/{name}.md  # Rendered strategy sources
├── curations/
│   ├── pending/                     # Curated but not yet executed
│   ├── running/                     # Currently executing
│   └── completed/                   # Finished curations
├── data/
│   ├── pending-skills/              # Awaiting user review
│   └── pending-strategies/          # Awaiting user review
└── skills/                          # Installed skills
```

### 11.2 SQLite Schema

```mermaid
erDiagram
    trajectories {
        text session_id PK
        text project_id
        text session_dir
        int turn_count
        text metadata_json
        text updated_at
    }

    pipeline_runs {
        text run_id PK
        text project_id
        text status
        int pid
        int requested_stop
        text progress_json
        text outputs_json
    }

    artifacts {
        text artifact_id PK
        text run_id FK
        text artifact_type
        text name
        text content
        text content_digest
        text validation_level
        text trust_tier
        text safety_gate_status
        text provenance_json
        text embedding_json
    }

    pcr_fragments {
        text fragment_id PK
        text artifact_id FK
        text procedure
        text context
        text resultant
        real feedback_score
        text content_digest
        text validation_level
        text trust_tier
        text safety_gate_status
        text provenance_json
        text embedding_json
        text lexical_text
    }

    operators {
        text operator_id PK
        text artifact_id FK
        text title
        text procedure
        text context
        text outcome
        text normalized_intent
        text slot_signature
        real feedback_score
        text validation_level
        text trust_tier
        text safety_gate_status
        text provenance_json
    }

    curation_sessions {
        text session_id PK
        text query
        text curation
        text operator_plan_json
        real confidence
        int should_abstain
        text abstain_reason
        text status
    }

    curation_feedback {
        text feedback_id PK
        text session_id FK
        text feedback_text
        text failure_stage
        int should_abstain
        text summary_json
    }

    curation_feedback_steps {
        text step_feedback_id PK
        text feedback_id FK
        text operator_id
        text verdict
        text failure_stage
        real predicted_success
        real predicted_confidence
    }

    operator_reliability {
        text operator_id PK
        int selection_count
        int helped_count
        int hurt_count
        int unused_count
        int retrieval_miss_count
        int execution_miss_count
        int abstain_count
        real calibration_error_sum
        real brier_score_sum
    }

    pipeline_runs ||--o{ artifacts : "produces"
    artifacts ||--o{ pcr_fragments : "decomposes into"
    artifacts ||--o{ operators : "synthesizes"
    curation_sessions ||--o{ curation_feedback : "receives"
    curation_feedback ||--o{ curation_feedback_steps : "details"
    operators ||--o| operator_reliability : "tracks"
    trajectories ||--o{ pipeline_runs : "feeds"
```

## 12. Feedback Loop

```mermaid
flowchart TD
    User[User Feedback] --> Resolve[Resolve Step Feedback]
    Resolve --> PerStep[Write curation_feedback_steps]
    Resolve --> FeedbackRow[Write curation_feedback]

    PerStep --> Reliability[Update operator_reliability]
    Reliability --> Counters[helped / hurt / unused / missing counts]
    Reliability --> Calibration[calibration_error + brier_score]
    Reliability --> Derived[Derive empirical_reliability + abstain_probability]

    Derived --> Gate[Dynamic Governance Gate]
    Gate -->|next curation| Retrieval[Retrieval eligibility]

    subgraph "Verdict Types"
        V1[helped]
        V2[hurt]
        V3[unused]
        V4[missing]
    end

    subgraph "Failure Stages"
        F1[retrieval]
        F2[execution]
        F3[mixed]
    end
```

Per-step causal feedback marks individual operators as `helped`, `hurt`, `unused`,
or `missing`. Misses are attributed to `retrieval`, `execution`, or `mixed` failure
stages. Reliability aggregates track calibration error and Brier score.
`operators.feedback_score` is a derived compatibility score from these reliability
metrics rather than a direct text-sentiment delta.

## 13. Skill Installation

```mermaid
flowchart TD
    Ref[SkillRefItem] --> HasPath{path exists locally?}
    HasPath -->|Yes| HasSkillMD{Contains SKILL.md?}
    HasSkillMD -->|Yes| CopyLocal[Copy to skills/ dir]
    HasSkillMD -->|No| Skip[Return 'skipped']
    HasPath -->|No| HasURL{url present?}
    HasURL -->|Yes| Download[Download HTTPS ZIP]
    Download --> Extract[Extract to skills/ dir]
    HasURL -->|No| Skip

    CopyLocal --> Installed[Return 'installed']
    Extract --> Installed
```

The installer supports both local source paths (from the local runtime) and
remote HTTPS ZIP archives (legacy server mode), enabling fully offline operation
apart from provider API calls.

## 14. CLI Commands

The `ratchet` CLI (`ratchet/client/cli.py`) provides:

| Command | Description |
|---------|-------------|
| `status` | Check plugin installation, provider keys, session counts |
| `configure` | Set provider API keys and client options |
| `login` | Legacy shim -- points to `configure` for local setup |
| `profile` | View or update user profile (language, level, style) |
| `pipeline-status` | Show active or recent runs with run dirs and heartbeat age |
| `pipeline-inspect` | Show timeline events, failure summary, LLM calls, and artifact paths |
| `pipeline-logs` | Tail or follow a run's `worker.log` |
| `debug` | Collect local run evidence and write a debug bundle directory |
| `debug-bundle` | Create a raw directory with run evidence |

Pipeline operations are run through the hook system and `run_pipeline.py`:
- `wisdom-gen` -- trigger pipeline, poll status, save outputs
- `wisdom-curate` -- retrieve and rank knowledge for a query
- `wisdom-feedback` -- submit feedback on curated results

## 15. Testing

| Test File | Coverage |
|-----------|----------|
| `test_local_runtime.py` | Full lifecycle: ingest, pipeline, curation, feedback, stop, install |
| `test_local_setup.py` | Provider key validation |
| `test_pipeline_constraints.py` | Pipeline configuration constraints |
| `test_shared_env.py` | Shared environment variable handling |
| `test_operator_graph.py` | Operator graph: facet retrieval, governance gating, PageRank, wave planning, causal feedback |
| `test_runtime_cli_integration.py` | End-to-end CLI: pipeline, curate, install, feedback, reranking |
| `test_hook_contracts.py` | Hook execution paths and contracts |
| `test_skill_wrappers.py` | Skill enhancement and wrapping |
| `test_plugin_contracts.py` | Plugin integration contracts |

Tests use `FakeLocalLLM` for deterministic, network-free execution that validates
ranking, persistence, and feedback behavior without provider dependencies.

## 16. Known Limitations

- Distillation uses heuristic clustering and structured LLM passes, not learned models
- PCR generation is consolidator-derived rather than fully model-generated
- Feedback weighting is heuristic
- Dependency graphs are shallow and mostly sequential
- Retrieval is exact (SQLite-backed), not ANN-backed
- Generation is lightly used in the local pipeline

These are acceptable trade-offs for a local-first OSS runtime that provides
clustered distillation, async runs, durable state, a safety-gated operator graph,
topological wave planning, cheatmap generation, and a causal feedback loop.
