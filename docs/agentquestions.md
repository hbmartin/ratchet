# Why AI Agents Keep Asking the Same Questions

Apr 6, 2026•

![Ani Galstian](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Foraw2u2c%2Fproduction%2F68545e0f765ac7ec41ac8be27ff7164b3e21a0b9-288x288.png&w=48&q=75)

Ani Galstian

![Why AI Agents Keep Asking the Same Questions](https://cdn.sanity.io/images/oraw2u2c/production/e45013a564909fdced7b511a733da1f57e8fac82-1600x900.svg)

AI coding agents forget project context because they operate on stateless inference with session-scoped memory, requiring developers to re-establish architecture, conventions, and dependencies at every session boundary.

## TL;DR

AI coding agents lose context because model weights are frozen, context windows rebuild from scratch, and most tools do not write cross-session memory by default. Manual files like AGENTS.md help, but they drift and consume tokens. Platform-level persistent context reduces repeated re-explanation by maintaining codebase understanding across sessions.

## Why Every Session Starts Over

The experience is universal: open a new session with an AI coding agent, ask it to extend the authentication module, and watch it suggest a pattern the team abandoned six months ago. Explain the service architecture again. Clarify the naming conventions again. Point out that the shared validation library exists again.

A recent [developer survey](https://survey.stackoverflow.co/2025/) quantifies part of that frustration: 66% of developers identify AI solutions that are "almost right, but not quite" as their single biggest frustration with AI coding tools. That "almost right" output is a direct symptom of missing context. The AI produces syntactically valid code that misses project-specific architectural intent.

AI agent persistent context is the capability that separates tools requiring constant hand-holding from tools that carry architectural understanding across sessions. This guide explains why agents forget, what the repetition costs, how manual workarounds function, where they break down, and what platform-level solutions look like when persistent context is handled at the architecture level. Augment Code's Context Engine is one approach to this problem, semantically indexing and mapping code relationships across 400,000+ files using semantic dependency graph analysis rather than relying on session-scoped retrieval alone. [Intent](https://www.augmentcode.com/product/intent) builds on that foundation: its coordinator, implementor, and verifier agents all share the same Context Engine understanding, so persistent context scales across coordinated multi-agent workflows without multiplying the re-explanation problem.

### See how Intent's agents share persistent codebase understanding across coordinated workflows.

[Build with Intent](https://www.augmentcode.com/product/intent)

Free tier available · VS Code extension · Takes 2 minutes

## Why AI Coding Agents Forget Your Architecture

AI agent memory loss comes from five architectural constraints that reinforce each other. Model weights are [frozen](https://www.redhat.com/en/topics/cloud-native-apps/stateful-vs-stateless) after training, so project-specific knowledge cannot be written into parameters during a conversation. Every message triggers a new API call where the full [chat history](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) is re-submitted as a fresh inference request. What feels like a continuous conversation is actually a reconstruction. As conversations grow, the model discards older content through compaction or hard truncation. Even within a single session, this compression loses granularity. Closing a session erases everything because no tool writes to external storage by default. And codebase indexing, while useful for retrieval, does not create persistent memory: Cursor describes its [indexing approach](https://cursor.com/help/customization/indexing) as a way to find code quickly, and GitHub confirms that [indexed repositories](https://docs.github.com/en/copilot/concepts/context/repository-indexing) are not used for model training.

These constraints compound. Indexing improves what enters the context window, but does not prevent that context from evaporating when the session ends. Larger context windows delay within-session truncation, but do not create cross-session persistence. No single layer solves the problem because the failure modes operate at different scopes.

| Failure Mode                 | Mechanism                                                                                                   | Scope                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------ |
| Stateless inference          | Model weights frozen post-training; no real-time parameter updates                                          | Fundamental architecture |
| Context rebuilt per API call | Full conversation history re-sent on every call; no server-side session state                               | Per-request              |
| Context window overflow      | Rolling token buffer truncates oldest messages; attention dilution precedes hard cutoff                     | Within-session           |
| No persistent storage        | No database or file write on session end; context evaporates                                                | Cross-session            |
| Indexing without memory      | Semantic search retrieves snippets into context window on demand; no persistent architectural understanding | Cross-session            |

## The Productivity Cost of Re-Explaining Context Every Session

Repeated context setup costs real time, even if the exact share attributable to re-explaining architecture is difficult to isolate from other AI-related overhead. Every new session requires developers to re-supply service architecture, coding conventions, database schemas, deprecation status of abstractions, and team-specific rationale behind architectural decisions: categories of context that a human teammate would retain across conversations.

### The Best Available Measurement

A 2025 randomized controlled study involving 16 experienced open-source developers completing 246 tasks across AI-assisted and control conditions found that developers using AI tools took **19% longer** to complete tasks than those who did not, as summarized in an [industry analysis](https://www.infoq.com/news/2025/07/ai-productivity/) of the results.

For a standard 2-hour focused development block, a 19% overhead corresponds to roughly 20-25 minutes of additional time. That estimate reflects total AI-related overhead, including prompting, waiting for generations, and correcting context-misaligned output. For a team of 10 engineers across a two-week sprint, assuming each developer runs roughly one AI-assisted focused session every other working day, that overhead translates to roughly 2-3 full engineering days lost to AI-related friction. Most of that friction manifests as re-establishing context, correcting misaligned output, and verifying suggestions against architectural intent. Teams where developers use AI tools more frequently per day would see proportionally higher costs. A separate [ecosystem survey](https://blog.jetbrains.com/research/2025/10/state-of-developer-ecosystem-2025/) reinforces this pattern, identifying context switching as becoming more prominent with career seniority, which suggests the developers with the deepest architectural knowledge are the ones most affected.

The perception gap matters because teams often evaluate these tools by feeling rather than by task completion time. The cost compounds further in multi-agent workflows where a coordinator, multiple implementors, and a verifier each need the same architectural understanding. Without persistent context shared across agents, every agent in the pipeline requires its own re-explanation cycle.

## Manual Fixes: AGENTS.md, Context Files, and Memory Directories

Manual context files inject project-specific information into the model's context window at session start, working around the absence of persistent AI agent memory. The ecosystem has produced both cross-tool and tool-specific formats.

### AGENTS.md: The Cross-Tool Standard

[AGENTS.md](https://www.augmentcode.com/guides/how-to-build-agents-md) is an open, tool-agnostic standard for providing instructions to AI coding agents. Released by OpenAI in August 2025 and donated to the Agentic AI Foundation under the Linux Foundation in December 2025, the format has been adopted by more than 60,000 open-source projects. Codex CLI, GitHub Copilot, Cursor, Windsurf, Amp, Jules, and Devin all read AGENTS.md natively. Claude Code uses CLAUDE.md as its primary format, though teams can reference AGENTS.md from within it. Augment Code also supports and documents the format.

A research study across [10 repositories](https://arxiv.org/html/2601.20404v2) and 124 PRs found AGENTS.md files associated with median wall-clock time decreasing by approximately 28.64% and output token consumption decreasing by approximately 16.58%.

The key distinction from README.md is audience and purpose. AGENTS.md targets AI coding agents specifically, documenting build commands, test runners, conventions, and constraints for autonomous operation rather than human onboarding.

### Tool-Specific Context Files

Each major AI coding tool has its own context file format, creating a fragmented landscape. The table below lists the primary file formats and their current status.

| File Format                     | Tool           | Status              | Key Detail                                                                                                                                |
| ------------------------------- | -------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| .cursor/rules/\*.mdc            | Cursor         | Current recommended | YAML frontmatter with alwaysApply flag; conditional loading                                                                               |
| CLAUDE.md                       | Claude Code    | Active              | Injected at session start; consumes token budget regardless of task relevance                                                             |
| .github/copilot-instructions.md | GitHub Copilot | Active              | Repository-wide instructions file; path scoping via applyTo frontmatter supported in \*.instructions.md files under .github/instructions/ |
| .windsurfrules                  | Windsurf       | Active              | User-defined rules; Cascade can separately generate auto-memories from conversations                                                      |
| GEMINI.md                       | Gemini CLI     | Active              | Also read by GitHub Copilot's coding agent                                                                                                |

Anthropic describes `CLAUDE.md` as part of its broader [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) approach to session injection. GitHub Copilot supports [custom instructions](https://docs.github.com/en/copilot/tutorials/use-custom-instructions) for path-scoped files. Windsurf's Cascade adds a separate [memory layer](https://docs.windsurf.com/plugins/cascade/memories) that auto-generates conversation-derived context.

### Community-Built Memory Patterns

Beyond tool-specific files, developers have built directory-based memory systems to manage context manually. The [memory bank](https://github.com/vanzan01/cursor-memory-bank) pattern, as referenced in Cursor's community forum, is a directory-based system that provides persistent context across sessions using structured files and Plan/Act modes.

A second pattern uses running documentation: when the agent invokes tools incorrectly, teams [record corrections](https://forum.cursor.com/t/community-tips-tricks/78165) in a file so future sessions can reuse the fix instead of relearning it.

### Where to Start if You Have No Context Files

Teams starting from zero should begin with a single AGENTS.md file at the repository root. Start with build and test commands so the agent can verify its own output. Then add architectural boundaries documenting which services own which domains. Follow with active conventions covering naming patterns, error handling standards, and deprecated patterns to avoid. Keep the file under 200 lines to limit token overhead and review it monthly against recent PRs to catch drift. If the team uses multiple AI tools, add the tool-specific format for the primary tool alongside AGENTS.md rather than maintaining duplicate content across formats.

## Where Manual Context Files Break Down

Manual context files improve on pure session-based prompting, but they introduce failure modes that get worse as codebases and teams grow.

### Staleness and Semantic Drift

Context files describe the codebase as it existed when written. As the codebase evolves, those files silently diverge from reality. This failure has been described as [context rot](https://www.camel-ai.org/blogs/brainwash-your-agent-how-we-keep-the-memory-clean): low-signal redundant information polluting the context and reducing the agent's ability to recall critical details, choose the right tools, or follow instructions correctly.

### Token Budget Exhaustion

Every line in a context file consumes tokens from the model's working memory. That overhead reduces space available for the actual task. Large always-on rule files are effectively permanent prompt overhead.

### Maintenance Overhead Becomes Its Own Job

Keeping context files accurate requires ongoing manual effort that competes with development work. The burden scales with codebase complexity and never reaches zero. Teams often end up maintaining the scaffolding alongside the software itself.

### Confident Hallucination From Outdated Context

The most operationally dangerous failure mode is confidence. Stale context files do not necessarily make the AI uncertain; they can make it confidently wrong. Consider an example: the context file states that the auth service uses JWT-based session tokens, but the team migrated to OAuth with opaque tokens three months ago. The agent generates a complete JWT verification middleware with full confidence, passing initial review because the code is syntactically correct and follows good patterns. The bug surfaces only in integration testing or production, hours after the PR merges.

Community discussions include [stale cutoffs](https://www.reddit.com/r/AI%5FAgents/comments/1rc7tzx/whats%5Fyour%5Fkill%5Fswitch%5Fstrategy%5Ffor%5Fagents%5Fin/) as a defensive measure when memory references appear outdated, but this is anecdotal rather than benchmark evidence.

The following table summarizes each failure mode, its root cause, and practical impact.

| Failure Mode            | Root Cause                                                | Impact                              |
| ----------------------- | --------------------------------------------------------- | ----------------------------------- |
| Staleness / drift       | No automatic sync between files and codebase evolution    | Agent follows abandoned patterns    |
| Token exhaustion        | Large files displace task context within fixed windows    | Reduced output quality              |
| Maintenance overhead    | Manual review cycle scales with complexity                | Developer time diverted from code   |
| Team inconsistency      | No shared, synchronized context source across developers  | Divergent AI behavior per developer |
| No automatic updates    | Human must detect and correct drift manually              | Delayed error correction            |
| Confident hallucination | AI acts on outdated information without uncertainty flags | Production-impacting errors         |

### Explore how Intent's living specs and coordinated agents eliminate context drift across multi-agent workflows.

[Build with Intent](https://www.augmentcode.com/product/intent)

Free tier available · VS Code extension · Takes 2 minutes

ci-pipeline

···

$ cat build.log | auggie --print --quiet \\

 "Summarize the failure"

Build failed due to missing dependency 'lodash'
in src/utils/helpers.ts:42

Fix: npm install lodash @types/lodash

## Platform-Level Fixes: How ADEs Handle Persistent Context

AI-powered development environments address agent context management at the architecture level. An [academic survey](https://arxiv.org/html/2508.11126v1) provides a useful taxonomy for classifying how different tools approach persistent context across three tiers.

### Tiers A and B: Transient Context and Embedding-Based Search

Tools in Tier A (GitHub Copilot, Codeium) use transient methods such as sliding windows or dynamic token budgeting; the repository index may persist on disk, but the agent's understanding is rebuilt fresh each session. Cursor and Windsurf sit a tier above, maintaining persistent indexes but rebuilding agent context through retrieval each session. Cursor describes its [codebase understanding](https://www.cursor.com/features) as powered by semantic search, while community requests for cross-session [persistent memory](https://forum.cursor.com/t/project-specific-context-memory-ai-should-remember-project-history/136157) remain open. Windsurf also confirms that its tool [indexes codebases](https://docs.windsurf.com/context-awareness/overview) and performs retrieval-augmented generation.

Aider operates differently: it uses a session-scoped structural summary rather than cross-session memory.

### Tier C: Persistent Knowledge Graph With Cross-Session Memory

Augment Code's Context Engine approaches context through a real-time semantic index that maintains a live understanding of the codebase across repositories, services, and history. The [Context Engine](https://www.augmentcode.com/context-engine) maintains a real-time knowledge graph with cross-service dependency tracking across 400,000+ files.

Open source

augmentcode/review-pr★32

[Star on GitHub](https://github.com/augmentcode/review-pr?utm%5Fsource=blog&utm%5Fmedium=cta&utm%5Fcampaign=github&utm%5Fcontent=why-ai-agents-repeat-questions)

The system continuously maintains commit history, codebase patterns, external sources, and tribal knowledge derived from codebase analysis. [Context Lineage](https://www.augmentcode.com/blog/announcing-context-lineage) connects agents to repository history so they can reason about the intent behind past changes alongside what changed.

Intent extends this persistent context into coordinated multi-agent workflows. Its coordinator agent analyzes the codebase through Context Engine before generating a spec and delegating tasks to implementor agents, each of which inherits the same architectural understanding. The verifier agent then checks results against the living spec using the same context foundation. Because every agent in the pipeline reads from a shared knowledge graph rather than rebuilding context independently, the re-explanation problem does not multiply with each additional agent. That coordination overhead is most valuable for cross-service features where multiple agents touch interdependent code; for single-file edits or small-repo workflows where session-scoped context is sufficient, the added orchestration layer is unnecessary.

This approach has tradeoffs. Initial indexing time for large repositories can take minutes to hours depending on codebase size and complexity. The knowledge graph's quality depends on what is already captured in code, commits, and documentation; undocumented tribal knowledge still requires manual context files. And persistent context introduces a new trust question: developers need to verify that the knowledge graph reflects current architectural reality, especially after major refactors or migrations.

Deployment supports both local and [remote server](https://docs.augmentcode.com/context-services/mcp/overview) configurations. The [MCP server](https://www.augmentcode.com/product/context-engine-mcp) also allows teams using Claude Code, Cursor, and other MCP-compatible clients to access Context Engine's persistent understanding.

The following table compares how each platform handles persistent context.

| Platform       | Primary Mechanism                                        | Cross-Session Persistence                                                          | Documented Scale                     |
| -------------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------ |
| Augment Code   | Knowledge graph + semantic dependency analysis           | Yes, automatic agent memories                                                      | 400K-500K+ files                     |
| Cursor         | Embedding-based semantic search + grep                   | Index persists; agent memory session-scoped                                        | Not specified                        |
| Windsurf       | RAG with M-Query techniques                              | Cascade adds multi-step support; codebase indexing documented                      | \~10,000 files at 10GB RAM           |
| GitHub Copilot | Semantic code search index                               | Repository index persists; cross-session agent memory available via Copilot Memory | Multiple repositories can be indexed |
| Aider          | Tree-sitter structural parsing + graph ranking algorithm | Session-scoped repo map/context                                                    | Whole-repo structural summary        |

### Why Automated Indexing and Manual Files Are Complementary

Even automated indexing has boundaries. A post on the challenges of [going AI-native](https://www.augmentcode.com/blog/hardest-part-about-going-ai-native) notes that the Context Engine can surface only what is already captured and recorded.

The AGENTS.md format addresses this gap through two buckets. Bucket 1 is what the agent can already see: code, file structure, dependencies, and git history. Bucket 2 is what the agent cannot discover independently: deployment procedures, internal tool patterns, and operational knowledge. That second bucket still belongs in AGENTS.md regardless of platform. Intent's living specs add a third layer by capturing evolving implementation intent that updates as agents complete work. The coordinator and implementors stay aligned on what should be built without manual re-synchronization.

## Evaluation Criteria for Persistent Context AI Coding Tools

Choosing a tool that handles AI agent persistent context well requires evaluating specific capabilities beyond marketing claims. The criteria that matter most depend on team context: solo developers and small teams should prioritize criteria 1-3 (indexing depth, cross-session memory, multi-repo support) because these address the core re-explanation problem. Larger teams should weight criteria 6, 8, and 9 (security, multi-agent coordination, governance) more heavily because context fragmentation across developers and agents becomes the dominant bottleneck at scale.

1. **Codebase indexing depth**: Does the tool index the full workspace, or only open files? Practical test: ask about a file not opened in the current session
2. **Cross-session memory**: Does context survive a tool restart? Practical test: reopen the next day and ask about a decision from the previous session
3. **Multi-repository understanding**: Can the tool reason across repository boundaries? Practical test: trace a data flow crossing a service boundary
4. **Architectural awareness**: Does generated code respect established patterns and layering? Research on [AI-generated code](https://www.infoq.com/presentations/ai-coding-agents/) points to signs of more duplicate code and churn, citing GitClear findings
5. **Context window efficiency**: Does the tool retrieve precisely or fill the window indiscriminately? Effective systems retrieve relevant context semantically or [flag uncertainty](https://thenewstack.io/memory-for-ai-agents-a-new-paradigm-of-context-engineering) rather than hallucinating
6. **Privacy and security controls**: Where is code processed? Security certifications, clear training-data terms, and documented data retention practices matter, especially in regulated industries
7. **IDE integration**: Does the tool cover the full workflow or only code completion? Full [development environments](https://www.augmentcode.com/product/ide-agents) matter because development work extends beyond the editor
8. **Multi-agent coordination**: When multiple agents work in parallel, do they share context or operate in isolation? Practical test: run two agents on related tasks and check whether they produce conflicting implementations
9. **Team-scale governance**: Can team standards be configured centrally and applied consistently across developers?

When using Augment Code's Context Engine, teams evaluating criteria 1-3 can test those capabilities directly because the system maintains a real-time knowledge graph with cross-service dependency tracking and cross-session memories. Intent addresses criterion 8 by routing all coordinated agents through the same Context Engine, so the coordinator, implementors, and verifier share architectural understanding without independent re-explanation cycles. The MCP server also lets teams test persistent context without changing their primary IDE.

## Test Cross-Session Context Before Your Next Sprint

The tradeoff in AI agent persistent context is straightforward. Manual files give developers control, but they create maintenance work that grows with codebase complexity. Session-scoped tools reduce some setup work, but they still force repeated re-explanation whenever the session resets. Multi-agent workflows amplify both problems because each agent in the pipeline needs the same architectural understanding.

A practical next step is to write a focused AGENTS.md that covers only what agents cannot discover on their own. Then test current tooling for cross-session memory, multi-repository understanding, and architectural awareness by closing it today and asking about yesterday's decisions tomorrow.

### See how Intent's agents share persistent codebase context across coordinated workflows.

[Build with Intent](https://www.augmentcode.com/product/intent)

Free tier available · VS Code extension · Takes 2 minutes

## FAQ

### Why does my AI coding agent forget context even within a single session?

### Does a larger context window solve the persistent context problem?

### Should teams maintain both AGENTS.md and use a platform with automated indexing?

### How much time does maintaining manual context files require?

### Can AI agents update their own context files automatically?

### How does Intent use persistent context across multiple agents?

## Related

* [8 Best AI Coding Assistants and Their Best Use Cases](https://www.augmentcode.com/guides/8-top-ai-coding-assistants-and-their-best-use-cases)
* [13 Best AI Coding Tools for Complex Codebases in 2026](https://www.augmentcode.com/guides/13-best-ai-coding-tools-for-complex-codebases)
* [AI Coding Assistants for Large Codebases: A Complete Guide](https://www.augmentcode.com/guides/ai-coding-assistants-for-large-codebases-a-complete-guide)
* [Claude Code vs Augment Code](https://www.augmentcode.com/guides/claude-code-vs-augment-code)
* [GitHub Copilot vs Augment Code: Enterprise AI Comparison](https://www.augmentcode.com/guides/github-copilot-vs-augment-code)

### Written by

![Ani Galstian](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Foraw2u2c%2Fproduction%2F68545e0f765ac7ec41ac8be27ff7164b3e21a0b9-288x288.png&w=128&q=75)

#### Ani Galstian

Ship more code with our free agent orchestrator app.

Download for Mac

Get Started

## Give your codebase the agents it deserves

Install Augment to get started. Works with codebases of any size, from side projects to enterprise monorepos.

[Install Augment](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/install) · [Contact Sales](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/contact)

[![Augment Code](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/augment_code_wordmark.svg?dpl=dpl_57rvxnxKLuPgstHsFXFvc863SeFH)](/)

### PRODUCT

* [Agent](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/product/ide-agents)
* [Intent](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/product/intent)
* [Code Review](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/product/code-review)
* [Slack](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/product/slack)
* [CLI](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/product/CLI)
* [Pricing](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/pricing)

### RESOURCES

* [Customers](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/customers)
* [Docs](https://docs.augmentcode.com/)
* [Blog](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/blog)
* [Guides](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/guides)
* [Learn](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/learn)
* [Tools](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/tools)
* [AI Engineering Playbook](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/resources/ai-powered-engineering-at-scale)

### COMPANY

* [Careers](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/careers)
* [Press Inquiries](mailto:press@augmentcode.com)
* [Press Kit](https://www.dropbox.com/scl/fo/pt4cxyhlyug03qpu19m66/AMYHXqBCjQdjhx8heH2TrJ0?rlkey=u8esym6obngbl1g77ft9r97pm&st=jejivpse&dl=1)
* [Contact Sales](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/contact)
* [Contact Support](https://support.augmentcode.com/)
* [Changelog](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/changelog)
* [Privacy & Security](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/security)
* [Trust Center](https://trust.augmentcode.com/)
* [Status Page](https://status.augmentcode.com)

### LEGAL

* [Cookie Policy](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/legal/cookie-policy)
* [Privacy Policy](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/legal/privacy-policy)
* [SLA and Support Policy](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/legal/sla-and-support-policy)
* Terms of Service

[![Augment Code](https://www.augmentcode.com/guides/why-ai-agents-repeat-questions/augment_code_wordmark.svg?dpl=dpl_57rvxnxKLuPgstHsFXFvc863SeFH)](/)

© 2026 Augment Code. All rights reserved.

DARK

LIGHT

SYSTEM
