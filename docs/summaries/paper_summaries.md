# Paper Summaries: 2025-2026 Agentic AI Research

## 1. Memento 2: Learning by Stateful Reflective Memory (Jan 2026)
**Core Concept:** Introduces the **Stateful Reflective Decision Process (SRDP)**, a formal model that treats agent memory as a control object. It bridges the gap between empirical "reflection" and formal Reinforcement Learning (RL).
**Key Mechanism:** The **Read-Write Reflective Learning** loop.
- **Read:** Policy improvement via retrieval of relevant past experience.
- **Write:** Policy evaluation via storing new interaction outcomes.
**Impact:** Provides mathematical convergence guarantees that a memory-embedded agent will reach optimal behavior as its experience grows, without needing to update model parameters.

## 2. SkillFlow: Benchmarking Lifelong Skill Discovery (April 2026)
**Core Concept:** Shifts focus from *using* tools to *discovering and maintaining* them. Introduces a benchmark of 166 tasks across 20 families.
**Key Mechanism:** **Domain-Agnostic Execution Flow (DAEF)**. Agents must solve tasks, externalize lessons into "skill patches," and reuse them.
**Impact:** Reveals a "Capability-Utility Gap"—many models can load skills but struggle to gain actual utility from them. Claude Opus 4.6 showed a +8.43 point gain, while others regressed.

## 3. SRA-Bench: Skill Retrieval Augmentation (April 2026)
**Core Concept:** Identifies the bottleneck in scaling agent capabilities. As libraries grow to thousands of skills, "Context Stuffing" (putting all tools in the prompt) fails.
**Key Findings:** The primary failure mode is **"Skill Loading Hallucination"**—the agent fails to judge *when* a skill is needed or *which* one to load.
**Impact:** Proposes that agents need "Need-Awareness" and "Incorporation Logic" rather than just better retrieval algorithms.

## 4. OrgAgent: Company-Style Hierarchical Organization (April 2026)
**Core Concept:** Proposes a three-layer hierarchy for multi-agent systems: **Governance**, **Execution**, and **Compliance**.
**Key Findings:** Hierarchical organization improves performance (up to 102%) while significantly reducing token consumption (up to 74%) compared to flat "chat-room" architectures.
**Impact:** Establishes that **organizational structure** is as important as the underlying model for complex reasoning.

## 5. SagaLLM: Transactional Guarantees for Agents (March 2025)
**Core Concept:** Applies the **Saga Pattern** from distributed systems to agentic workflows.
**Key Mechanism:** Implements persistent memory, automated compensation (rollback), and independent validation agents.
**Impact:** Solves the problem of "broken workflows" where one failed step in a multi-agent plan corrupts the entire state. Ensures consistency and recovery in long-running tasks.

## 6. Bi-Level Knowledge Transfer (BiKT) for MARL (2025/2026)
**Core Concept:** Enables zero-shot generalization in multi-agent environments by separating **Individual Skills** from **Team Tactics**.
**Key Mechanism:** A Bi-Level Decision Transformer that infers the required team coordination (Tactic) before selecting individual agent behaviors (Skills).
**Impact:** Allows agents trained on one set of tasks to coordinate effectively in entirely new environments by transferring the "coordination logic" separately from the "action logic."

## 7. FORGE: Fragment-Oriented Molecular Optimization (May 2026)
**Core Concept:** Moves from "global generation" to **"local editing"** using a two-stage Rank-and-Replace framework.
**Key Mechanism:** Identifies "fragile" fragments (Where to edit) using context-aware attribution, then generates specific replacements (How to edit).
**Impact:** Eliminates chemical hallucinations and the need for expensive text-based training data by using rule-verified "edit pairs."
