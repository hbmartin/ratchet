# Decomposing agent knowledge into retrievable procedure-context-outcome fragments

**AI coding agents today overwhelmingly load monolithic instruction files at session start, but a convergence of academic research and practical tooling now makes fragment-level knowledge retrieval viable.** The most promising pattern decomposes validated knowledge into atomic units indexed along procedure (how), context (when/where), and outcome (what result) dimensions—mirroring patterns from proposition-based retrieval, knowledge graph triples, and cognitive architecture research. This approach can reduce context window consumption by 47–90% while improving retrieval precision by 35% or more, based on benchmarks from Dense X Retrieval, Anthropic's contextual retrieval, and Cursor's dynamic context discovery.

The fundamental constraint driving this work is what researchers call the **"context window economy"**: every token loaded into an agent's context displaces potential reasoning capacity. Loading a 3,000-token skill file when only a 200-token procedure fragment is relevant wastes 93% of that allocation. The solution requires decomposing knowledge into atomic units, indexing them across multiple dimensions, and retrieving only what's needed at inference time.

---

## The atomic knowledge unit is the key abstraction

The most structured decomposition pattern comes from the **Knowledge Activation Framework** (arXiv:2603.14805), which defines Atomic Knowledge Units (AKUs) with seven components: intent, procedure, tools, metadata, governance, continuations, and validators. This maps cleanly to the procedure-context-outcome triple the user describes. Intent and procedure capture "how," metadata and governance encode "when/where," and validators and continuations specify "what result" and "what happens next." AKUs form a composable knowledge graph that agents traverse at runtime, loading only the fragments relevant to the current task.

This framework addresses what its authors call the **"institutional impedance mismatch"**—the gap between what LLMs know parametrically and what organizations need them to know about internal practices. AKUs follow a three-stage pipeline: **codification** (capturing expert knowledge), **compression** (decomposing into atomic units), and **injection** (loading fragments into context at the right moment).

The academic foundation for atomic decomposition comes from **Dense X Retrieval** (Chen et al., EMNLP 2024), which demonstrated that proposition-level retrieval—where documents are broken into self-contained atomic factual statements—yields **35% improvement in Recall@5** over passage-level retrieval. Each proposition is atomic (cannot be split further), self-contained (includes all necessary context), and minimal (encodes one distinct piece of meaning). Their Propositionizer model (fine-tuned Flan-T5-Large) can decompose passages at scale, and the approach is implemented in both LlamaIndex (`DenseXRetrievalPack`) and LangChain.

---

## Three practical decomposition patterns have emerged

### Pattern 1: Proposition-level decomposition for declarative knowledge

Dense X Retrieval established the hierarchy: **documents → passages → sentences → propositions**. Each passage yields roughly 6 propositions; each sentence yields about 2. For a coding agent's skill file, this means a rule like "When writing TypeScript React components, use functional components with hooks, follow the naming convention ComponentName.tsx, and ensure all props have TypeScript interfaces" decomposes into three independent propositions, each retrievable by different queries.

**Question-based retrieval** (Raina & Gales, FEVER 2024) extends this by generating synthetic questions from each atom. Since user queries are questions while atomic facts are statements, embedding-space alignment improves when retrieval targets match query form. This added another **14% improvement in R@1** over direct atom retrieval.

### Pattern 2: Hierarchical task network decomposition for procedural knowledge

For procedural knowledge—the "how" dimension—**Hierarchical Task Networks (HTNs)** provide the most rigorous decomposition. ProcLLM (arXiv:2511.07568) demonstrated that encoding procedures as HTN decompositions (abstract tasks → subtasks → primitive actions) significantly improves agent task success across multiple base LLMs. Each method in the network specifies a head task, preconditions, and ordered subtasks, naturally encoding the procedure-context-outcome triple.

**LEGOMem** (arXiv:2510.04851) takes a complementary approach, decomposing past task trajectories into reusable memory units at two levels: full-task memories (description + high-level plan) and subtask memories (localized agent behavior + tool use + observations). This yielded **12+ percentage point improvement** in task success rates and up to **16.2% reduction** in execution steps. The key insight is separating the orchestrator's view (what to do) from the worker's view (how to do each step).

### Pattern 3: Temporal knowledge graph triples for contextual knowledge

**Graphiti/Zep** (arXiv:2501.13956, github.com/getzep/graphiti) implements the most mature triple-based representation: entity nodes connected by semantic edges as fact triples, with a **bi-temporal model** tracking when facts were true and when they were ingested. Every edge has validity intervals, enabling queries like "what was our error-handling convention before the refactor?" This scored **94.8%** on the Deep Memory Retrieval benchmark.

**Mem0** (arXiv:2504.19413, github.com/mem0ai/mem0) takes a similar approach with relationship triplets (source, relation, destination), automatic extraction from conversations, and dual retrieval combining entity-centric graph traversal with semantic triplet matching. It achieved **26% accuracy improvement** over OpenAI Memory on LOCOMO with **90% lower token usage** than full-context approaches.

---

## How leading coding tools handle knowledge retrieval today

The current generation of AI coding tools reveals an industry in transition from monolithic loading to selective retrieval.

**Claude Code** pioneered the hierarchical approach with CLAUDE.md files at user, project, and subdirectory levels, but loads them fully at session start (first 200 lines/25KB). Its newer **SKILL.md system** implements genuine progressive disclosure: at startup, only the skill name and description (~100 tokens) enter the system prompt. The full skill body loads only when Claude's reasoning determines it's relevant. This is the closest production implementation of the procedure-context-outcome pattern—the description encodes context (when to use), the body encodes procedure (how), and validators can encode expected outcomes. Skills can bundle scripts, references, and assets in subdirectories, accessed only during execution.

**Cursor** moved furthest toward dynamic retrieval with its **four rule activation types**: always-apply, glob-attached (auto-loaded when matching files are referenced), agent-requested (LLM decides based on description), and manual. Its January 2026 Skills system (v2.4+) reads `.claude/skills/`, `.codex/skills/`, and `.agents/skills/` directories with the same progressive disclosure pattern. Most significantly, Cursor's **dynamic context discovery** (2025-2026) syncs tool descriptions and definitions to local filesystem files, then lets the agent discover relevant context via grep and semantic search—reducing **total agent tokens by 46.9%** for MCP tool calls in A/B testing.

**Aider** takes a fundamentally different approach with its **repository map**. Instead of loading skill files, it builds an AST-parsed graph of the entire codebase using tree-sitter, then applies **PageRank** (via NetworkX) to rank files by relevance to the current conversation. A binary search algorithm fits the most important content within a configurable token budget. This graph-ranked approach dynamically adapts the "context" dimension without requiring explicit decomposition—the map itself is a compressed representation of structural knowledge.

**Cline and Roo Code** implement a **structured memory bank** pattern with typed markdown files (activeContext.md, productContext.md, decisionLog.md, systemPatterns.md). This is a manual decomposition along dimensions—but the files are loaded wholesale, not at fragment level. The pattern has spawned dozens of community variants (cursor-memory-bank, RooFlow, etc.), suggesting strong demand for structured knowledge decomposition even without automated retrieval.

---

## Code-specific retrieval goes beyond text chunking

For coding knowledge specifically, several approaches achieve sub-document retrieval that could support procedure-context-outcome indexing.

**AST-based chunking** (cAST, arXiv:2506.15655, github.com/yilinjz/astchunk) parses code into Abstract Syntax Trees and recursively creates self-contained, semantically coherent units at function/class boundaries. This yielded **+4.3 points Recall@5** on RepoEval and **+2.67 points Pass@1** on SWE-bench. The complementary **code-chunk** project (github.com/supermemoryai/code-chunk) adds contextual metadata—each chunk includes file path, scope chain, entity signatures, and dependency information. This metadata naturally encodes the "context" dimension.

**Anthropic's contextual retrieval** prepends chunk-specific explanatory context (50-100 tokens) to each chunk before embedding, using the full document as context for a Claude Haiku call. For codebases specifically, this achieved **95.26% Pass@10** with reranking. Combined with contextual BM25, it delivered a **67% reduction** in top-20 retrieval failures. The prepended context effectively separates "what this code does" (procedure) from "where it fits" (context).

**Microsoft's GraphRAG** (github.com/microsoft/graphrag) extracts entities, relationships, and claims from text, builds community hierarchies via Leiden detection, and generates multi-level summaries. For codebases, this captures cross-file relationships, API dependencies, and architectural patterns that naive chunking misses entirely. **CodexGraph** adapted this pattern specifically for code agents, achieving **69.7% bug localization** via multi-hop graph traversals.

| Strategy | Granularity | Context preservation | Best for |
|----------|------------|---------------------|----------|
| AST-based (cAST) | Function/class | High (semantic boundaries) | Code-specific fragments |
| Proposition-level | Atomic facts | Medium (decontextualized) | Knowledge-dense instructions |
| Contextual retrieval | Chunk + prepended context | High (document-aware) | Mixed code and documentation |
| GraphRAG | Entity-relationship | Very high (structural) | Cross-file architecture knowledge |
| RAPTOR | Multi-level tree | Very high (hierarchical) | Complex multi-step reasoning |

---

## Cognitive architectures provide the theoretical backbone

The **CoALA framework** (arXiv:2309.02427) from Princeton provides the definitive taxonomy for agent memory, decomposing it into working memory (context window), episodic memory (past experiences), semantic memory (facts and knowledge), and procedural memory (how to perform tasks). This maps directly to the procedure-context-outcome model: procedural memory encodes "how," episodic memory provides "when/where" context from past experience, and semantic memory captures "what result" as validated facts.

**Voyager** (arXiv:2305.16291, github.com/MineDojo/Voyager) demonstrated the most successful skill library pattern for agents. Each skill is stored as executable code with a natural language description, indexed by embedding similarity, and composed by calling simpler skills. When facing a new task, the agent retrieves the **top-5 relevant skills** and composes them. The ODYSSEY extension built 40 primitive skills and 183 compositional skills, showing that finite task complexity plateaus (LEGOMem's MACLA found the same plateau at **187 procedures** for ALFWorld tasks).

**MemGPT/Letta** (arXiv:2310.08560, github.com/letta-ai/letta) introduced the most sophisticated self-managing memory, where agents actively curate their own knowledge using tool calls (`memory_insert`, `memory_replace`, `memory_rethink`). The OS-inspired architecture treats core memory as RAM (always in context), archival memory as disk (vector-searched on demand), and recall memory as conversation logs. This is significant because it shifts from static decomposition to **agent-directed knowledge management**—the agent itself decides which fragments to load, archive, or restructure.

---

## Implementing procedure-context-outcome triples in practice

Based on the research, a concrete implementation would combine several patterns:

- **Decomposition layer**: Use Dense X Retrieval's Propositionizer to break monolithic skill files into atomic propositions, then classify each along the procedure-context-outcome dimensions using a lightweight LLM classifier. The AKU schema provides the target structure: intent and procedure fields capture "how," metadata and governance capture "when/where," and validators capture "what result."

- **Indexing layer**: Store triples in a hybrid system combining vector embeddings (for semantic retrieval of procedure fragments), a knowledge graph (for structural relationships between context conditions), and BM25 (for exact matches on tool names, error codes, and API identifiers). Graphiti's temporal model adds validity windows so outdated practices are flagged but not deleted.

- **Retrieval layer**: Implement progressive disclosure following the SKILL.md pattern—load only triple metadata (~100 tokens per unit) into the system prompt at session start, then retrieve full triple content on demand based on the agent's current task context. Use Anthropic's contextual retrieval approach to prepend structural context to each fragment before embedding.

- **Recomposition layer**: At query time, retrieve relevant fragments across all three dimensions and assemble them into a coherent instruction block. The agent receives only the procedures relevant to its current task, the context conditions that apply to the current codebase state, and the expected outcomes for validation.

Key repositories to build on include **Graphiti** (github.com/getzep/graphiti) for temporal knowledge graph infrastructure, **code-chunk** (github.com/supermemoryai/code-chunk) for AST-aware code decomposition, the **Dense X Retrieval Propositionizer** for atomic text decomposition, and **Letta** (github.com/letta-ai/letta) for self-managing memory architecture.

---

## Conclusion

The field has converged on several clear principles. First, **atomic units outperform document-level retrieval** by 35% or more—the debate is over granularity, not direction. Second, **three memory types are necessary**: episodic (experiences/context), semantic (facts/outcomes), and procedural (skills/how-to), mapping naturally to the procedure-context-outcome triple. Third, **progressive disclosure beats full loading**—Claude Code's SKILL.md and Cursor's dynamic context discovery both demonstrate 47–90% token savings. Fourth, **temporal awareness matters**: knowledge changes, and systems like Graphiti that track validity windows prevent stale practices from contaminating agent behavior.

The gap in the current landscape is precisely what the user identifies: no production system yet implements a unified procedure-context-outcome triple store with fragment-level retrieval for coding agents. The closest implementations are Claude Code's SKILL.md (progressive disclosure without dimensional indexing), Graphiti (temporal triples without procedure-specific decomposition), and Dense X Retrieval (atomic propositions without dimensional classification). Combining these three approaches—SKILL.md's progressive disclosure architecture, Graphiti's temporal triple store, and Dense X Retrieval's atomic decomposition—would create the system the user envisions.
