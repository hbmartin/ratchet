# Building a graph-powered AI agent skill router

The most effective architecture for dynamically loading AI agent skills via a graph database combines **three core patterns**: a knowledge graph schema modeling skills, intents, and dependencies as typed nodes and edges; embedding-based "Tool RAG" for semantic skill retrieval at query time; and topological sorting of dependency subgraphs to generate ordered execution plans — what you're calling a Cheatmap. This approach has emerged as the dominant paradigm across major frameworks (LangChain, Semantic Kernel, Anthropic's agent architecture) because it solves the "tool overload" problem: at **100+ tools, naive approaches where all tools are loaded into context fail**, with accuracy dropping as low as 13% in large toolsets. Graph-backed routing with embedding retrieval recovers accuracy to **43-74%** while cutting token usage by **75-90%**.

The key insight from recent research is that this isn't purely theoretical — Microsoft's Semantic Kernel evolved through five generations of planners before converging on a hybrid of LLM function calling plus RAG-based skill retrieval. Neo4j Labs has shipped purpose-built libraries (agent-memory, create-context-graph) for exactly this pattern. The technology stack is mature enough for production use today.

---

## Modeling skills, intents, and dependencies in a graph

The schema design is the foundation. The graph should contain five primary node types — **Skill**, **Intent**, **Context**, **Parameter**, and **Workflow** — connected by typed, weighted edges that encode routing logic, dependencies, and data flow.

**Skill nodes** represent atomic agent capabilities and carry properties including `name`, `description`, `category`, `embedding` (a vector of the description), `costEstimate`, `confidenceThreshold`, `enabled`, and `executionType` (sync/async/streaming). **Intent nodes** capture parsed user goals with `utterancePatterns` and their own embeddings. **Context nodes** model prerequisite environmental conditions like authentication state or user permissions.

The critical edges are:

- `RESOLVED_BY` (Intent → Skill): weighted with `confidence` and `matchType` (exact, semantic, pattern) — the primary routing edge
- `DEPENDS_ON` (Skill → Skill): typed as `hard`, `soft`, or `conditional`, with optional `condition` expressions and `dataFlow` annotations
- `REQUIRES_CONTEXT` (Skill → Context): prerequisite state that must be active
- `SIMILAR_TO` (Skill → Skill): precomputed similarity scores for fallback routing
- `SUB_INTENT_OF` (Intent → Intent): hierarchical intent decomposition

A concrete Cypher schema creation looks like this:

```cypher
CREATE (s:Skill {
  id: 'skill_web_search', name: 'Web Search',
  description: 'Performs web searches using search APIs',
  category: 'retrieval', executionType: 'async',
  costEstimate: 0.02, confidenceThreshold: 0.7,
  enabled: true, embedding: $vector
})

CREATE (i:Intent {id: 'intent_find_info', name: 'FindInformation',
  description: 'User wants to find specific information',
  embedding: $intentVector
})

CREATE (i)-[:RESOLVED_BY {confidence: 0.95, priority: 1}]->(s)
```

Vector indexes on both Skill and Intent embeddings enable semantic matching. Neo4j supports native **HNSW vector indexes** (up to 4,096 dimensions, cosine/euclidean similarity), which can be created with a single statement and queried inline with graph traversals — this hybrid graph+vector capability is what makes the architecture work. The pattern of encoding knowledge into graph relationships rather than inferring it at query time is crucial: `(:Intent)-[:RESOLVED_BY]->(:Skill)<-[:DEPENDS_ON]-(:Skill)` is semantically richer and faster to traverse than computing relationships dynamically.

---

## How modern frameworks handle dynamic tool selection at scale

The state of the art has converged on what practitioners call **Tool RAG** — embedding tool descriptions into vectors and using semantic search to retrieve relevant tools at runtime, analogous to document RAG but for capabilities. Every major framework now implements some version of this pattern.

**LangChain** introduced a middleware system where a secondary LLM (a cheaper model like GPT-4.1-mini) filters tools before the primary agent sees them. The `llmToolSelectorMiddleware` accepts parameters like `maxTools` and `alwaysInclude`, reducing the tool payload by 75-90% per request. LangGraph extends this with `Command()` objects that enable imperative routing decisions inside graph nodes — a shift from declarative edge definitions to dynamic, state-aware routing.

**Microsoft Semantic Kernel** traveled a revealing evolutionary path through five planner generations (Action → Sequential → Stepwise → Handlebars → Function Calling) before deprecating all custom planners in favor of native LLM function calling combined with a **ContextualFunctionProvider**. This experimental but production-ready component vectorizes all function descriptions into an in-memory vector store and semantically matches conversation context against available functions, advertising only the **top-K most relevant** to the model. The SK team explicitly states that "presenting the model with 2K functions is problematic because the model will typically get confused."

**Anthropic** shipped a production solution marking tools with `defer_loading: true` — tools remain discoverable but don't consume context until the agent searches for them via regex or BM25 ranking. This achieved an **85% reduction in token usage** while improving Opus 4 accuracy from **49% to 74%**.

Beyond framework-level solutions, several architectural patterns handle tool selection at scale:

- **Hierarchical routing** (AnyTool): a three-tier architecture where a meta-agent generates category agents, which manage domain-specific tool agents — tested successfully with **16,000+ APIs**
- **Graph RAG-Tool Fusion** (Toolshed): constructs knowledge graphs of inter-tool relationships and augments vector-retrieved seed tools via graph traversal, achieving **46-56% absolute improvement** on benchmarks
- **Generative tool tokens** (ToolGen): maps each tool to a unique vocabulary token so selection becomes next-token prediction — tested with **47,000 tools** but with scalability tradeoffs
- **Fine-tuned specialist models** (Gorilla): a LLaMA-7B model trained specifically for API calls across 1,600+ APIs, outperforming GPT-4 on API usage benchmarks

The practical recommendation for most systems is to start with embedding-based Tool RAG (it provides the best balance of simplicity and effectiveness), then layer on graph-based dependency traversal for workflow generation.

---

## Generating a Cheatmap from graph traversal

The Cheatmap — a step-by-step execution plan specifying which skill to read at each step, why, and with what relevance score — is generated through a three-stage pipeline: **retrieve** relevant skills via semantic search, **resolve** their dependencies via graph traversal, and **order** via topological sort.

**Stage 1: Skill retrieval.** Given a parsed user intent, perform a hybrid search combining vector similarity (cosine against skill embeddings) with graph-based lookup (direct `RESOLVED_BY` edges). Neo4j's Cypher 25 syntax supports this in a single query:

```cypher
WITH $queryEmbedding AS queryVector
MATCH (s:Skill)
SEARCH s IN (VECTOR INDEX `skill-embeddings` FOR queryVector LIMIT 10) SCORE score
WHERE s.enabled = true AND score > 0.7
RETURN s.name, s.description, score ORDER BY score DESC
```

**Stage 2: Dependency resolution.** For each retrieved skill, traverse `DEPENDS_ON` edges recursively to collect the full dependency subgraph. Filter by active context (only include skills whose `REQUIRES_CONTEXT` prerequisites are satisfied):

```cypher
MATCH path = (s:Skill {name: $skillName})-[:DEPENDS_ON*]->(dep:Skill)
WHERE ALL(ctx IN [(dep)-[:REQUIRES_CONTEXT]->(c) | c.id] WHERE ctx IN $activeContextIds)
RETURN dep.name, dep.id, length(path) AS depth ORDER BY depth DESC
```

**Stage 3: Topological ordering.** Apply Kahn's algorithm or Neo4j's GDS topological sort to produce a valid execution order. Neo4j's GDS library is remarkably efficient here: it processes **50,000 dependencies in 51ms** and **1 million+ in 696ms**, while equivalent Cypher queries fail to complete at these scales. The GDS algorithm also computes `maxDistanceFromSource` for each node, which naturally groups skills into parallelizable "waves" — skills at the same distance can execute concurrently.

```python
# Wave-based execution using NetworkX
import networkx as nx

def generate_cheatmap(skill_subgraph, intent_embedding, skill_embeddings):
    cheatmap = []
    for wave_idx, generation in enumerate(nx.topological_generations(skill_subgraph)):
        wave_steps = []
        for skill_id in generation:
            relevance = cosine_similarity(intent_embedding, skill_embeddings[skill_id])
            deps = list(skill_subgraph.predecessors(skill_id))
            wave_steps.append({
                "step": skill_id,
                "wave": wave_idx,
                "relevance_score": round(relevance, 3),
                "reason": f"Required by {deps}" if deps else "Direct intent match",
                "parallel": len(generation) > 1
            })
        cheatmap.append(sorted(wave_steps, key=lambda x: -x["relevance_score"]))
    return cheatmap
```

Each Cheatmap entry should annotate **why** a skill is included (direct intent match, transitive dependency, or contextual prerequisite), its relevance score, and whether it can execute in parallel with sibling steps. Conditional branches are modeled via `DEPENDS_ON` edges with `type: 'conditional'` and a `condition` expression — at runtime, the agent evaluates the condition against current state and includes or skips the branch.

---

## Scoring relevance with hybrid signals

No single scoring method is sufficient. The best implementations combine **four signals** using either Reciprocal Rank Fusion (RRF) or weighted linear combination.

**Embedding similarity** (weight ~0.40) provides the semantic backbone. Production systems use models like `text-embedding-3-small` or `all-MiniLM-L6-v2` (384 dimensions, 23MB) with cosine similarity. The SkillX system demonstrates a refined approach: retrieve top-100 candidates via FAISS HNSW, filter to those with cosine similarity **≥ 0.45 AND within 0.08 of the best match** (adaptive selectivity), deduplicate at pairwise cosine > 0.95, then apply **Maximal Marginal Relevance** (λ=0.75) to balance relevance with diversity, returning up to 8 skills.

**Graph-based scoring** (weight ~0.25) captures structural importance. **Personalized PageRank** is the strongest signal here — it biases the random walk toward the user's current context/task node, producing scores that reflect both global skill importance and local relevance. Neo4j GDS supports this natively with a `sourceNodes` parameter. Betweenness centrality identifies "bridge" skills that connect many dependency chains, while simple graph distance (hop count from intent node) provides a fast heuristic.

**Keyword matching** (weight ~0.20) via BM25 catches exact terminology that embeddings might miss. BM25F extends this by weighting skill name matches higher than description matches — a skill named exactly what the user asked for should rank highest regardless of embedding distance.

**Usage history** (weight ~0.15) applies collaborative filtering: skills frequently co-invoked in similar contexts get a boost. This signal improves over time as the system accumulates usage data.

The combined scoring function with RRF fusion:

```python
def hybrid_score(intent, skill, graph, history):
    semantic = cosine_similarity(embed(intent), skill.embedding)
    graph_rank = personalized_pagerank(graph, source=intent_node)[skill.id]
    keyword = normalize(bm25_score(intent, skill.description))
    usage = min(history.get(skill.id, 0) / max_usage, 1.0)

    final = 0.40 * semantic + 0.25 * normalize(graph_rank) + 0.20 * keyword + 0.15 * usage
    return final if final >= 0.35 else 0.0  # Confidence threshold
```

The **confidence threshold of 0.35** is a practical starting point observed across multiple implementations (OpenCode Agent Skills, production embedding-based systems). Skills below this threshold are excluded from the Cheatmap entirely.

---

## Lazy loading skills with three-tier progressive disclosure

The dominant caching architecture uses a **three-tier progressive disclosure** model that minimizes token consumption while maintaining full skill discoverability.

**Tier 1 — Metadata only** (~10-20 tokens per skill): Always loaded into the system prompt. Contains only `name` and a one-line `description` from YAML frontmatter. With 200 skills, this consumes roughly **2,000-4,000 tokens** — a tiny fraction of modern context windows versus the **40,000+** tokens required to load everything. This tier serves as the "index" the agent scans to decide what to look up.

**Tier 2 — Full documentation** (~200-2,000 tokens per skill): Loaded on-demand when the scoring pipeline identifies a skill as relevant. Contains the complete SKILL.md body — usage instructions, parameter schemas, examples, edge cases. The retrieval overhead is minimal: **~2ms for relevance detection + ~50ms for schema fetch + ~1ms for registration = ~53ms total**.

**Tier 3 — Executable registration**: Only when the agent commits to invoking a skill. Tool functions are registered with the LLM, subprocess isolation ensures safety with timeouts.

Production statistics confirm that **most conversations use 0-3 skills**, meaning 95-100% of the library stays at Tier 1. This yields a **~97% reduction** in per-conversation token cost compared to loading everything.

For caching, a **Redis-backed embedding cache** eliminates redundant embedding computations. LangChain's `CacheBackedEmbeddings` wraps any embedder with a key-value store — first call takes ~1,800ms (compute + cache), subsequent calls take **~1ms** (cache hit). For frequently accessed skill chains, cache the complete intent → skill-chain mapping with tag-based invalidation: when any skill in the chain updates, publish an invalidation event via Redis Pub/Sub to all nodes.

Precomputation strategies include: pre-computing all skill embeddings at startup and rebuilding the FAISS/HNSW index, pre-computing PageRank scores for the entire skill graph (these change only when skills are added/removed), and caching common Cheatmaps for high-frequency intents using the Asteria semantic caching approach (similarity threshold ~0.85 for cache hits).

---

## Choosing a graph database for production

The choice depends on scale, latency requirements, and existing infrastructure.

| Factor | Neo4j | Amazon Neptune | Memgraph | TigerGraph |
|--------|-------|---------------|----------|------------|
| Best for | Richest ecosystem, developer experience | AWS-native, managed infrastructure | Sub-millisecond latency | Massive scale (trillions of edges) |
| Query language | Cypher (native) | openCypher, Gremlin, SPARQL | Cypher-compatible (~95%) | GSQL, openCypher |
| Vector search | Native HNSW (v5.11+) | Neptune Analytics | Supported | TigerVector (v4.2+) |
| Latency | Sub-100ms typical | Variable (managed) | **Sub-ms to low-ms** | Fast parallel |
| AI framework integration | **Best** — LangChain, LlamaIndex, CrewAI, Google ADK, MCP server | Bedrock Knowledge Bases, Strands SDK | MCP support, GraphRAG | Agentic GraphRAG |
| Graph algorithms | GDS library (PageRank, topological sort, SCC) | Neptune Analytics | MAGE library (30+) | Built-in parallel |
| Cost | Community free / Enterprise | Pay-per-use (unpredictable I/O) | Community free / Enterprise | Community free |

**For most teams building this system, Neo4j is the recommended starting point.** It offers the deepest AI framework integration (the `neo4j-labs/agent-memory` library is purpose-built for this exact use case), native vector indexes that enable hybrid graph+vector queries in a single Cypher statement, and the GDS topological sort algorithm that handles dependency ordering at scale. The `create-context-graph` CLI tool from Neo4j Labs can scaffold an entire domain-specific graph application with FastAPI backend, Next.js frontend, and agent memory integration.

**Memgraph is the choice when sub-millisecond latency is non-negotiable** — its in-memory C++ architecture delivers results up to **120x faster** than Neo4j for certain operations, and its Cypher compatibility (~95%) means queries are largely portable. The tradeoff is a smaller ecosystem and memory-bound scalability.

**Amazon Neptune fits AWS-native environments** where managed infrastructure and Bedrock integration matter more than ecosystem breadth. **TigerGraph excels at massive scale** — its MPP architecture handles trillions of relationships, and TigerVector integrates vector search directly into GSQL as callable functions for true single-query hybrid operations.

---

## Reference implementations that validate this architecture

Several production and research systems confirm the viability of this approach. **Microsoft's Semantic Kernel** evolved through five planner generations before converging on the same architecture described here: LLM function calling + RAG-based skill retrieval via `ContextualFunctionProvider`. The **Toolshed** framework (arXiv:2410.14594) implements advanced RAG-Tool Fusion with knowledge graphs of inter-tool relationships, achieving 46-56% absolute improvement on tool selection benchmarks. **KnowAgent** (NAACL 2025) uses external action knowledge bases to constrain agent planning trajectories, significantly reducing planning hallucinations.

On the open-source side, **ToolBench** (ICLR 2024 Spotlight) provides 16,464 real-world REST APIs with a neural API retriever for benchmarking. **Neo4j's agent-memory** library implements graph-native memory with multi-stage entity extraction and MCP server integration across six agent frameworks. The **SkillX** system (arXiv:2604.04804) demonstrates production-grade skill retrieval using FAISS HNSW indexes with hybrid thresholding and MMR diversity selection.

The emerging consensus across academia and industry is clear: flat tool lists don't scale, knowledge graphs reduce hallucination by constraining the planning space, and hybrid retrieval (embeddings + graph structure + keywords) outperforms any single signal. The Cheatmap pattern — retrieve relevant skills, resolve dependencies, topologically sort, annotate with scores and rationale — is the natural synthesis of these findings into a practical, implementable system.

## Conclusion

The architecture described here is not speculative — each component has production implementations and benchmark validation. The key design decisions are: use **Neo4j** (or Memgraph for latency-critical paths) with a five-node-type schema; implement **Tool RAG** with hybrid scoring combining embedding similarity, graph distance, BM25, and usage history; generate Cheatmaps via **topological sort** of dependency subgraphs with wave-based parallelization; and adopt **three-tier progressive disclosure** to minimize token consumption. The most underappreciated insight from this research is that graph-based dependency traversal and embedding-based skill retrieval are not alternatives but complements — embeddings find what's semantically relevant, while the graph ensures structural completeness by pulling in prerequisites and dependencies the embeddings would miss.
