# Gold Standard: Agent-Designing Agents (Self-Evolving Systems)
**Updated: June 2026**

### 1. The Core Paradigm: Deployment-Time Learning
The 2026 "Gold Standard" has shifted from pre-trained agents to agents that **design and repair themselves during execution**.
- **Self-Correction is Policy:** Following **Memento 2**, agent "reflection" is now formalized as a **Read-Write Reflective Learning** loop. Reflection is no longer a prompt trick; it is the mechanism of policy iteration in a non-stationary environment.
- **Zero Fine-Tuning:** Optimization occurs entirely in the "scaffold" (external skill files and stateful prompts), keeping the core LLM weights frozen.

### 2. Architectural Requirements
- **Stateful Reflective Decision Process (SRDP):** Agents must treat their external memory (Skills/Episodic logs) as part of the state. This restores the Markov property to the decision-making process.
- **Trajectory-to-Skill Transformation:** Agents must possess a "Refinement Module" that can distill a successful execution trace into a reusable, declarative skill (e.g., `SKILL.md` with structured YAML/Python).
- **Skill Discovery Protocol:** As established in **SkillFlow**, agents must solve tasks sequentially, identifying capability gaps and generating new "skill patches" autonomously.

### 3. Key Performance Metrics
- **Relative Improvement over Rounds:** The primary metric is no longer absolute accuracy, but the **delta in success** across $N$ reflective learning cycles (e.g., +116% relative gain on expert-level benchmarks).
- **Skill Utility vs. Usage:** Systems must differentiate between *loading* a skill and *successfully applying* it. High usage with low utility indicates "Skill Over-reliance."
