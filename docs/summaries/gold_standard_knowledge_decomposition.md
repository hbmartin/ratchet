# Gold Standard: Knowledge Decomposition (PCO Fragments)
**Updated: June 2026**

### 1. The PCO Triplet
The Gold Standard for agentic knowledge representation is the **Procedure-Context-Outcome (PCO) Fragment**.
- **Context:** The environmental state and user intent (The "Why" and "Where").
- **Procedure:** The sequence of atomic actions or code (The "How").
- **Outcome:** The success signal and semantic "lessons learned" (The "Result").

### 2. Localized Editing (Fragment-Oriented)
Following the **FORGE** framework, agents should avoid "Global Re-decoding" (rewriting everything).
- **Identify then Replace:** The agent first localizes the "fragile" part of a complex structure (code, molecule, or plan) and then applies a targeted edit.
- **Context-Aware Attribution:** Using signals like SME+ to determine how a specific fragment contributes to the overall goal within its unique environment.

### 3. Validated Knowledge Fragments
- **Rule-Verified Pairs:** Knowledge is stored as "Edit Pairs" (Low-performing state vs. High-performing state) that have been verified by an external oracle (linter, compiler, or property predictor).
- **Retokenization for Stability:** Use of specialized tokenizers (like QwenAtom or language-specific AST tokenizers) to ensure fragments retain their identity and meaning across different contexts.
