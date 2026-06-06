# Gold Standard: Skill Retrieval & Routing (SRA)
**Updated: June 2026**

### 1. Beyond "Context Stuffing"
The previous standard of placing all tool descriptions in the system prompt is deprecated. The 2026 Gold Standard utilizes **Skill Retrieval Augmentation (SRA)**.
- **Dynamic Skill Loading:** Agents only load the minimal subset of tools required for the current sub-task, preserving the context window for reasoning.
- **Three-Stage Pipeline:** Effective SRA follows the **SkillFlow** model:
    1. **Retrieval:** Finding relevant skills in a library of >10k items.
    2. **Incorporation:** A metacognitive "gate" decides if a skill is actually needed.
    3. **Application:** Executing the task using the loaded tool.

### 2. Behavioral Routing
- **Success-Conditioned Selection:** Retrieval is no longer based on semantic similarity (text matching) but on **Historical Success Rates**. The "Skill Router" selects the tool that has successfully solved the most similar *execution context* in the past.
- **Domain-Agnostic Execution Flow (DAEF):** Skills are organized into families sharing consistent workflows, allowing for better "In-Family" transfer learning.

### 3. Solving the "Metacognitive Bottleneck"
- **Need-Awareness:** The system must actively evaluate if the internal capabilities of the LLM are sufficient before triggering a retrieval.
- **Loading Hallucination Defense:** Implementation of verification layers to ensure the retrieved skill matches the current task constraints.
