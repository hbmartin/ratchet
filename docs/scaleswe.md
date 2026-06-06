# Immersion in the GitHub Universe: Scaling Coding Agents to Mastery

Jiale Zhao Guoxin Chen Fanzhe Meng Minghao Li Jie Chen Hui Xu Yongshuai Sun Wayne Xin Zhao Ruihua Song Yuan Zhang Peng Wang Cheng Chen Ji-Rong Wen Kai Jia

## Abstract

Achieving mastery in real-world software engineering tasks is fundamentally bottlenecked by the scarcity of large-scale, high-quality training data. Scaling such data has been limited by the complexity of environment setup, unit-test generation, and problem statement curation. In this paper, we propose Scale‑SWE, an automated, sandboxed multi‑agent workflow designed to construct high‑quality SWE data at scale. The system coordinates three specialized agents—for environment setup, test creation, and problem description synthesis—to process 6 million pull requests across 5.2k repositories, producing Scale‑SWE‑Data: 100k verified SWE instances, the largest such dataset to date. It substantially surpasses existing real‑world datasets in repository diversity and reflects realistic task complexity. We further demonstrate the dataset’s utility for training by distilling 71,498 high‑quality trajectories and fine‑tuning Qwen‑30B-A3B-Instruct to produce Scale‑SWE‑Agent. Our agent achieves a 64% resolve rate on SWE‑Bench‑Verified—a nearly three‑fold improvement over the base model. Scale‑SWE provides a scalable, reproducible approach for data construction to advance LLM‑based software engineering.

![[Uncaptioned image]](2602.09892v4/x1.png) [Model](https://huggingface.co/AweAI-Team/Scale-SWE-Agent) ![[Uncaptioned image]](2602.09892v4/x2.png) [Dataset](https://huggingface.co/collections/AweAI-Team/scale-swe) ![[Uncaptioned image]](2602.09892v4/x3.png) [Code](https://github.com/AweAI-Team/ScaleSWE)

## 1 Introduction

![Refer to caption](2602.09892v4/figures/performance.drawio.png)

Figure 1: Resolved rate vs. activated model size on SWE-bench Verified. The vertical axis denotes the percentage of resolved issues on the SWE-bench Verified benchmark. The horizontal axis represents the number of activated parameters in billions (B).

Recently, LLM-based code agents have garnered significant attention for their demonstrated potential in tackling complex software engineering (SWE) tasks \[Anthropic, [2025a](#bib.bib1), Google, [2025](#bib.bib11), OpenAI, [2025](#bib.bib20), Team et al., [2025b](#bib.bib28), Chen et al., [2025](#bib.bib4)\], as reflected in benchmarks like SWE-bench \[Jimenez et al., [2023](#bib.bib16)\] and its successors \[Zhang et al., [2025](#bib.bib42)\]. Yet the advancement of these agents is fundamentally constrained by the scarcity of high-quality training data. Unlike conventional code generation, SWE tasks necessitate operation within executable environments, requiring agents to navigate existing codebases, manage dependencies, and satisfy test suites. These inherent complexities render the systematic curation and validation of appropriate data a significant challenge.

Current methodologies for constructing SWE-style datasets predominantly rely on labor-intensive manual curation \[Pan et al., [2024](#bib.bib21)\] or on simplistic LLM-based \[Badertdinov et al., [2025](#bib.bib3)\] and rule-based synthesis \[Guo et al., [2025b](#bib.bib13)\]. Consequently, existing datasets are often limited in scale, diversity, and difficulty, or lack the executable environments and comprehensive test suites. This limitation persists despite the wealth of available real-world software artifacts, including code repositories, issue trackers, and commit histories, which remain largely untapped for building a scalable, realistic dataset. The absence of systematic, automated mining techniques has thus produced a clear disconnect between these raw software resources and the creation of robust, large-scale training data. This compelling need drives our work to develop an automated and reproducible approach for dataset construction.

However, the automatic construction of SWE datasets presents unique and significant challenges. First, environment configuration becomes a major hurdle as repository diversity increases, leading to highly heterogeneous and often fragile build processes \[Froger et al., [2025](#bib.bib9)\], which can be challenging even for experienced developers to set up correctly. Second, real-world repositories frequently lack sufficient, well-defined unit tests. While incorporating these repositories is essential to reduce data bias and achieve scale, generating comprehensive unit tests itself is a complex problem that demands interactive agentic execution and self-correction. Finally, a substantial portion of real-world pull requests either lack informative descriptions or are inherently unsuitable for SWE tasks. Therefore, generating high-quality, self-contained problem descriptions is challenging and requires agents to infer task intent by acquiring deep repository context through iterative sandbox exploration.

To overcome these challenges, in this paper, we introduce Scale-SWE, an automated, sandboxed multi-agent workflow designed for scalable, high-quality software engineering dataset construction. Our system coordinates three specialized agents: an environment builder agent that sets up isolated Docker environments, a unit-test creator agent that generates robust Pass-to-Pass (P2P) and Fail-to-Pass (F2P) test cases, and a problem statement agent that crafts self-contained task descriptions grounded in pull request content. By processing 6 million pull requests across 5,200 repositories, this workflow produces 100,000 verified instances, yielding the largest SWE dataset to date, which we call Scale-SWE-Data. This dataset surpasses prior real-world datasets in repository diversity and reflects realistic software engineering complexity, both in the number of file modifications required and the robustness of its unit tests.

To further demonstrate the utility of Scale-SWE-Data for model training, we distill 71,498 high-quality trajectories from a subset of 25,000 instances using DeepSeek-V3.2\. Fine-tuning Qwen3-30A3B-Instruct on this distilled data yields our Scale-SWE-Agent, which achieves a substantial performance boost on SWE-Bench-Verified, increasing the resolve rate from 22% to 60%. This result underscores the effectiveness of our dataset for training and enhancing LLM-based code agents.

To summarize, our contributions are as follows:

- We introduce Scale-SWE, an automated, sandboxed multi-agent workflow for scalable, high-quality software engineering dataset construction. It systematically coordinates three specialized agents for environment setup, unit-test generation, and problem description synthesis.
- We construct Scale-SWE-Data, the largest verified SWE dataset to date, comprising 100,000 real-world instances. It surpasses prior benchmarks in repository diversity and task complexity, supporting both evaluation and training for LLM-based code agents.
- We distill 71,498 high-quality trajectories from Scale-SWE-Data and fine-tune Qwen-30A3B-Instruct to create Scale-SWE-Agent. The agent substantially boosts performance on SWE-Bench-Verified, achieving a 64% resolve rate—a nearly three-fold improvement over the original backbone.

## 2 Scale-SWE: Software Task Scaling

![Refer to caption](2602.09892v4/figures/scale_swe.drawio.png)

Figure 2: The Sandboxed multi-agent system for Scale-SWE dataset construction. Starting from millions of raw GitHub pull requests, the pipeline employs a series of autonomous agents to transform high-quality PRs into executable software engineering tasks. The framework automates environment setup, unit test generation (Fail-to-Pass/Pass-to-Pass), and formal problem statement synthesis, ensuring the scalability and reproducibility of the distilled trajectories.

The core philosophy of Scale-SWE is to make use of a sandboxed multi-agent system to autonomously explore codebases and complete SWE data construction. Each SWE data instance encapsulates the necessary components: a docker image, a problem statement, and the validation unit tests (consisting of F2P and P2P unit tests). Our sandboxed multi-agent system offers significantly greater flexibility compared to prior rule-based construction methods. By shifting the construction burden to the agent, Scale-SWE enables the scaling of interactive environments while minimizing the heuristic bias inherent in rigid filtering pipelines. In what follows, we firstly introduce our sandboxed multi-agent system (Section [2.1](#S2.SS1 "2.1 Sandboxed Multi-agent System ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery")), and then detail by the data processing pipeline (Section [2.2](#S2.SS2 "2.2 Data Processing ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery")).

### 2.1 Sandboxed Multi-agent System

To scale the automated construction of software engineering tasks, we develop a sandboxed multi-agent system. This framework leverages collaborative agents to produce a large volume of SWE data with fully integrated, executable environments.

#### 2.1.1 The Overall Workflow

As illustrated in Figure [2](#S2.F2 "Figure 2 ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"), our sandboxed multi-agent system automates the construction of software engineering tasks through the coordinated execution of three specialized agents: the Environment Builder Agent (EBA), the Unit-test Creator Agent (UCA), and the Problem Statement Writer Agent (PSWA). Within this framework, the EBA generates reproducible, Docker-based execution environments from target repositories, providing the isolated and consistent runtime needed for scalable task validation. The UCA synthesizes comprehensive, executable test suites—including both Fail-to-Pass (F2P) and Pass-to-Pass (P2P) test cases—from pull requests and repository context, ensuring robust evaluation criteria. Finally, the PSWA produces high-quality, self-contained problem descriptions grounded in the executable test suites, guaranteeing semantic alignment between the problem statement and the validation requirements. The system is built upon SWE-agent \[Yang et al., [2024a](#bib.bib34)\] and powered by the DeepSeek language model family \[Liu et al., [2025](#bib.bib17)\] and Gemini3-Pro \[Google, [2025](#bib.bib11)\], with task instances generated using both DeepSeek v3.1 or DeepSeek v3.2, with the exception of PSWA, which utilizes Gemini3-Pro.

#### 2.1.2 Environment builder agent

The EBA is designed to automatically generate a reproducible, Docker-based execution environment from a target source code repository. By providing an isolated and executable sandbox, the EBA enables the scalable construction and validation of test samples for automated software engineering workflows.

Role Formulation. We define the core function of the EBA as the transformation of an initial, generic Docker environment into a specialized runtime container tailored to a specific repository. This process can be expressed as:

| 𝒟final\=EBA​(ℛ,𝒟init),\\mathcal{D}\_{\\text{final}}=\\text{EBA}(\\mathcal{R},\\mathcal{D}\_{\\text{init}}), | (1) |
| ------------------------------------------------------------------------------------------------------------- | --- |

where ℛ\\mathcal{R} denotes the input repository that the agent analyzes to infer dependencies and configuration logic, 𝒟init\\mathcal{D}\_{\\text{init}} is the base Docker image, and 𝒟final\\mathcal{D}\_{\\text{final}} is the resulting functional, ready-to-use container image.

Construction Process.In implementation, the EBA is initialized within a base Docker container containing the cloned repository. It begins by autonomously exploring the repository’s structure and analyzing configuration files—such as setup.py, pyproject.toml, and README.md—to infer project dependencies. Since Python projects lack a universal setup protocol, a standardized installation approach is insufficient. The agent must therefore interpret project-specific documentation and interactively resolve dependency conflicts by parsing terminal feedback. This feedback-driven, autonomous process enables flexible environment configuration, circumventing the limitations of static, rule-based methods (e.g., predefined pip install commands). Finally, we extract all executed commands from the agent’s trajectory and use an LLM to synthesize them into a reproducible Dockerfile.

Efficiently Scaling Environmental Diversity.While constructing a dedicated environment per pull request (PR) is straightforward, it is computationally prohibitive for large-scale evaluation. To scale across a diverse set of repositories, we sample at most ten PRs per repository for full environment construction via the EBA. This sampling strategy enables broader repository coverage while controlling resource costs. Note that ten PRs do not yield only ten task samples; multiple PRs can share the same environment if they originate from a similar runtime state, resulting in significantly more test samples than uniquely built environments. Specifically, for the remaining PRs, we execute tests in the “nearest” available Docker environment, determined by proximity in PR ID (as a proxy for repository timeline). If a PR fails the unit tests within its nearest available environment, it is discarded from the final dataset. Otherwise, the PR and its associated pre-established environment are retained as a valid test instance. On average, each repository contributes 19 test instances (see Table [2](#S2.T2 "Table 2 ‣ 2.4 Dataset Statistics and Trajectory Distillation ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery")), dramatically improving environment reuse and overall dataset diversity.

#### 2.1.3 Unit-test creator agent

The _unit-test creator agent (UCA)_ is designed to automatically generate comprehensive and executable test suites from target source code repositories and their associated pull requests. By synthesizing semantic PR information with dynamic repository context, the UCA enables the scalable construction of validated Fail-to-Pass (F2P) and Pass-to-Pass (P2P) test cases, which are essential for robust software engineering task evaluation.

Role Formulation. The core function of the UCA is to transform the provided pull request metadata and its associated code context into a comprehensive suite of executable unit tests. This process can be expressed as:

| 𝒰\=UCA​(ℳ,ℛ,𝒟final),\\mathcal{U}=\\text{UCA}(\\mathcal{M},\\mathcal{R},\\mathcal{D}\_{\\text{final}}), | (2) |
| -------------------------------------------------------------------------------------------------------- | --- |

where ℳ\\mathcal{M} denotes the input pull request metadata—including the title, description, and diff patches—that provides the semantic specification for test generation, ℛ\\mathcal{R} is the associated source repository that the agent analyzes to understand code structure and logic, 𝒟final\\mathcal{D}\_{\\text{final}} is the functional Docker environment built by the EBA, and 𝒰\\mathcal{U} is the resulting set of executable test cases. In this work, we adopt the SWE-bench protocol for unit tests, categorizing them into two types: Fail-to-Pass (F2P) tests, which initially fail on the original codebase and must pass after the bug-fixing patch to verify correctness; and Pass-to-Pass (P2P) tests, which are pre-existing passing tests that must continue to pass to ensure no regression is introduced.

Construction Process.A large proportion of GitHub repositories lack comprehensive unit tests, making the automated construction of both Fail-to-Pass (F2P) and Pass-to-Pass (P2P) test cases essential for creating valid Software Engineering (SWE) task instances. The UCA begins by analyzing structured metadata from a target PR, including its title, description, and diff patches. This input provides the necessary semantic grounding for the agent to comprehend the intent and scope of the proposed code changes. Building on this foundation, the agent performs an autonomous traversal of the associated repository to map its directory structure, identify key modules, and infer the underlying program logic and dependencies. However, generating effective unit tests presents a complex, stateful challenge that requires not only static code understanding but also dynamic behavioral validation. The agent must reason about cross-file interactions, data flow, exception handling, and edge cases—tasks that are difficult to accomplish through static analysis alone. To address this, the UCA is deployed within a secure, sandboxed execution environment (specifically, the Docker container 𝒟final\\mathcal{D}\_{\\text{final}} produced by the EBA). This sandbox grants the agent direct, real-time code execution privileges, enabling an interactive execute-analyze-refine loop. The agent can thus dynamically run its proposed tests, observe their outcomes, and iteratively revise the test logic, assertions, and fixtures. This closed-loop, feedback-driven methodology allows the UCA to produce robust, executable test suites.

#### 2.1.4 Problem Statement Writer Agent

The _problem statement writer agent (PSWA)_ is designed to automatically synthesize high-quality, self-contained task descriptions from raw pull requests and their associated test suites. By grounding the narrative in executable unit tests, the PSWA ensures semantic alignment between the problem specification and unit tests, thereby producing well-posed and tractable software engineering tasks.

Role Formulation. The core function of the PSWA is to generate a formal problem statement free of solution leakage according to pull request metadata and its corresponding test suite. This process can be expressed as:

| 𝒮\=PSWA​(ℳ,𝒰,ℛ,𝒟final),\\mathcal{S}=\\text{PSWA}(\\mathcal{M},\\mathcal{U},\\mathcal{R},\\mathcal{D}\_{\\text{final}}), | (3) |
| -------------------------------------------------------------------------------------------------------------------------- | --- |

where ℳ\\mathcal{M} denotes the input PR metadata—including its title, description, and diff patches—that provides initial contextual grounding; 𝒰\\mathcal{U} is the executable unit-test suite generated by the UCA, which ensures the problem statement aligns with the actual validation requirements; ℛ\\mathcal{R} is the associated source repository; 𝒟final\\mathcal{D}\_{\\text{final}} is the functional Docker environment built by the EBA; and 𝒮\\mathcal{S} is the resulting formal problem description that articulates the issue without exposing implementation details and consistent with unit-test at the same time.

Construction Process.Relying solely on raw PR descriptions as problem statements is fundamentally flawed due to their retrospective nature—they are often written after the fix is implemented and may leak solution details or reference internal artifacts. Moreover, a significant portion of high-quality PRs lack descriptions or are disconnected from original issue reports. To overcome these limitations, the PSWA is initialized with both the PR metadata and the executable unit tests produced by the UCA. Integrating the test suite into the prompt is critical because F2P tests may invoke functions or classes that do not exist in the original codebase; the generated problem statement must explicitly articulate these requirements to make the task tractable. Without this alignment, descriptions derived only from PR metadata often diverge from the actual failures captured by the tests. The agent thus synthesizes a coherent, self-contained narrative that specifies the expected behavior, any new interfaces required by the tests, and the context necessary for an external solver—all while deliberately omitting hints about the implementation. This process ensures that each synthesized task instance is both semantically precise and evaluation-ready, scaling the creation of SWE-bench-style problems from raw repository data.

For PSWA, we employ Gemini3-Pro, as our experiments indicate that it generates more consistent and rigorous problem statements while significantly minimizing information leakage.

Table 1: Detailed statistics of the Scale-SWE dataset. We report the mean and percentiles (P50, P75, P95) for code modification metrics and test case distributions.

| Metric         | Mean  | P50  | P75   | P95   |
| -------------- | ----- | ---- | ----- | ----- |
| Modified Files | 6.4   | 3.0  | 6.0   | 18.0  |
| Deleted Lines  | 54.9  | 1.0  | 10.0  | 119.0 |
| Added Lines    | 220.8 | 43.0 | 120.0 | 595.0 |
| Edited Lines   | 37.0  | 6.0  | 20.0  | 108.0 |
| Total Changes  | 312.7 | 63.0 | 167.0 | 867.0 |
| Fail-to-Pass   | 5.7   | 2.0  | 5.0   | 15.0  |
| Pass-to-Pass   | 209.0 | 68.0 | 178.0 | 793.0 |
| Total tests    | 214.7 | 72.0 | 185.0 | 801.7 |

### 2.2 Data Processing

Ensuring high data quality is the foremost priority in building a reliable dataset. This section details our curation methodology to achieve this goal.

Repository Selection.To assemble a comprehensive and high-quality corpus, we sourced repositories from two primary channels, illustrated in Figure [5](#A1.F5 "Figure 5 ‣ A.1 Scale-SWE workflow Overview. ‣ Appendix A Scale-SWE workflow details. ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"). First, we identified the repositories corresponding to the top 15,000 most-downloaded packages on the Python Package Index (PyPI), using data from [Top PyPI Packages](https://hugovk.github.io/top-pypi-packages/). Second, to capture notable projects beyond PyPI, we queried the [SEART](https://seart-ghs.si.usi.ch/) search engine with the following criteria: primary language as Python, a minimum of 5 contributors, at least 500 stars, and a creation date between January 1, 2015, and October 29, 2025\. This query returned 9,062 repositories. The initial union of these two sources yielded approximately 23,000 candidate repositories. We then applied a multi-stage filtering pipeline. First, to prevent data leakage from the evaluation benchmark, we excluded all PRs originating from repositories listed in SWE-Bench Verified. Second, we filtered to include only repositories with permissive open-source licenses. Finally, recognizing that a subset of repositories might be GPU-dependent, tutorial-based, or contain minimal source code, we performed a content-based filter. We extracted the README files from all remaining candidates and employed an LLM-as-a-judge approach to automatically exclude repositories deemed unsuitable for training.

Pull Request Filtering.We next extracted all pull requests merged into the “main” or “master” branches of the filtered repositories, resulting in a preliminary set of 6 million entries. To ensure quality, we utilized an LLM-as-a-judge to filter low-quality instances based on the available metadata: the git diff, the pull request description, and the merge commit message.

Cheating Prevention.During the evaluation phase, it is imperative to prevent the model from exploiting git commands (e.g., git log --all) to access ground truth solutions \[Xiao et al., [2026](#bib.bib32)\]. To address this, we execute a sanitization script immediately after initializing the task environment. This process, systematically removes metadata that follows the task’s parent commit. It performs a hard reset, deletes all remote references and tags, and purges internal git files (e.g., logs/, packed-refs, and various HEAD files), thereby eliminating any trace of future solution history.

![Refer to caption](2602.09892v4/figures/dataset_comparison_icml.png)

Figure 3: Distribution of bug categories across different datasets. The bar chart compares the percentage of ten bug types within SWE-bench Verified, SWE-Gym, SWE-smith, and Scale-SWE. The categories are defined as: API Mismatch (incompatible signatures or parameter errors); Logic Error (flawed conditionals or control flow); Input/Boundary (edge case mishandling or validation failures); Constructor (object initialization errors); Import Error (missing modules or undefined symbols); State Sync (inconsistent internal state); Mutability (unintended side effects); Spec Violation (non-compliance with protocols); I/O Resource (file system or stream errors); and Security (improper scoping or access control).

### 2.3 Dataset Quality Assurance

Rule-based Check. We implemented a rigorous filtering protocol based on test outcomes. We retained only those instances where: (1) all P2P tests pass and F2P tests fail on the original buggy codebase; and (2) all P2P and F2P tests pass upon application of the golden patch.

Expert Check. We engaged four senior Ph.D. students to manually audit 100 randomly sampled instances employing a cross-validation protocol. The audit confirmed that 94 instances were valid, featuring correct environments, unit tests, and problem statements. We attribute this high quality to three key factors: (1) We leveraged state-of-the-art models (e.g., Gemini 3 Pro) to synthesize accurate problem statements; (2) We employed an LLM-as-a-Judge approach to preemptively discard low-quality repositories and pull requests; and (3) We enforced a fixed execution order for P2P and F2P tests to prevent test pollution, where varying execution orders could otherwise lead to inconsistent results due to environment contamination.

### 2.4 Dataset Statistics and Trajectory Distillation

Ultimately, our agent-based construction pipeline yielded 100k successfully verified instances—the largest verified SWE benchmark to date. Leveraging our extensive collection of GitHub repositories, the resulting dataset achieves substantially greater repository diversity than existing SWE benchmarks, as detailed in Table [2](#S2.T2 "Table 2 ‣ 2.4 Dataset Statistics and Trajectory Distillation ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"). Unlike previous datasets that typically rely on synthetic generation or limited real-world sources, Scale-SWE is constructed entirely from 5.2k real repositories. This represents a 50% increase in repository count over the next largest real-world benchmark (SWE-rebench with 3.5k repositories). This scale and diversity ensure that our benchmark better reflects the complexity and variety of real-world software engineering tasks.

The statistical characteristics of Scale-SWE are presented in Table [1](#S2.T1 "Table 1 ‣ 2.1.4 Problem Statement Writer Agent ‣ 2.1 Sandboxed Multi-agent System ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"). The dataset presents non-trivial software engineering challenges. The median instance requires modifications to at least 3 files and the addition of 43 lines of code, reflecting the task complexity. For evaluation robustness, instances contain an average of over 200 Pass-to-Pass (P2P) tests (median: 68), providing strong protection against regression, while an average of 5.69 Fail-to-Pass (F2P) tests per instance validates whether the LLM successfully resolves the specific issue.

To construct the training corpus, we distilled agent trajectories from a subset of 25k instances using the high-performance expert model DeepSeek-V3.2\. For each instance, we conducted five independent sampling trials with a temperature of 0.95 and a maximum budget of 100 interaction turns. A trajectory was considered valid only if it culminated in a submission that passed all unit tests. This pipeline produced 71k high-quality trajectories totaling approximately 3.5 billion tokens. To ensure a fair comparison, we applied the identical pipeline to collect trajectories for SWE-Smith and SWE-Gym.

Figure [3](#S2.F3 "Figure 3 ‣ 2.2 Data Processing ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery") highlights the superior diversity of Scale-SWE. Synthetic datasets like SWE-smith exhibit a strong bias towards Logic Errors, failing to capture the intricacies of API Mismatches or State Synchronization issues common in large codebases. Similarly, SWE-Gym, despite being real-world sourced, suffers from low variety due to its restriction to only 11 repositories.

Conversely, Scale-SWE achieves a highly balanced distribution across all ten bug categories. By leveraging 5.2k real-world repositories and an automated environment-building pipeline, Scale-SWE effectively captures a wide array of defect types—from Constructor errors to Security flaws. This validates that scaling the source repositories and automating the execution pipeline are critical for synthesizing training data that faithfully represents real-world software evolution.

We adopt the bug taxonomy proposed in BugPilot \[Sonwane et al., [2025](#bib.bib24)\] and employ DeepSeek v3.2 to automatically annotate the training instances.

Table 2: Comparison of Scale-SWE with existing software engineering (SWE) benchmarks. We contrast datasets across key dimensions: the number of executable instances—defined as those equipped with a Dockerized environment and validated via Fail-to-Pass (F2P) and Pass-to-Pass (P2P) tests—primary data source, repository diversity, and trajectory count.

| Dataset                                               | Exec. instances | Primary Source | Repo. | Traj. |
| ----------------------------------------------------- | --------------- | -------------- | ----- | ----- |
| R2E-Gym \[Jain et al., [2025](#bib.bib15)\]           | 4.6k            | Synthetic      | 10    | 3.3k  |
| SWE-Gym \[Pan et al., [2024](#bib.bib21)\]            | 2.4k            | Real           | 11    | 491   |
| SWE-smith \[Yang et al., [2025a](#bib.bib36)\]        | 50k             | Synthetic      | 128   | 5k    |
| SWE-Mirror \[Wang et al., [2025a](#bib.bib29)\]       | 60k             | Synthetic      | 40    | 12k   |
| SWE-rebench \[Badertdinov et al., [2025](#bib.bib3)\] | 7.5k            | Real           | 3.5k  | N/A   |
| Scale-SWE                                             | 100k            | Real           | 5.2k  | 71k   |

Table 3: Performance comparison on SWE-bench Verified. We categorize models into proprietary systems, open-source methods, and size-matched baselines.

| Models                                                    | Base Model                 | SWE-bench (V) |
| --------------------------------------------------------- | -------------------------- | ------------- |
| Proprietary Models                                        |                            |               |
| GPT-5.2 Thinking \[OpenAI, [2025](#bib.bib20)\]           | \-                         | 80.0          |
| Claude Sonnet 4.5 \[Anthropic, [2025b](#bib.bib2)\]       | \-                         | 77.2          |
| Gemini 3 Pro \[Google, [2025](#bib.bib11)\]               | \-                         | 76.2          |
| MiniMax-M2.1 \[MiniMax AI, [2025](#bib.bib19)\]           | \-                         | 74.0          |
| GLM-4.7 \[Zhipu AI, [2025](#bib.bib43)\]                  | \-                         | 73.8          |
| DeepSeek-V3.2 \[Liu et al., [2025](#bib.bib17)\]          | \-                         | 73.1          |
| Kimi K2 Thinking \[Team et al., [2025a](#bib.bib26)\]     | \-                         | 71.3          |
| Open Source Methods                                       |                            |               |
| SWE-Gym-32B \[Pan et al., [2024](#bib.bib21)\]            | Qwen-2.5 coder             | 20.6          |
| SWE-Fixer-72B \[Xie et al., [2025](#bib.bib33)\]          | Qwen2.5-72B                | 32.8          |
| R2E-Gym-32B \[Jain et al., [2025](#bib.bib15)\]           | Qwen-2.5-Coder             | 34.4          |
| SWE-rebench-72B \[Golubev et al., [2025](#bib.bib10)\]    | Qwen2.5-72B-Instruct       | 39.0          |
| SWE-smith-32B \[Yang et al., [2025a](#bib.bib36)\]        | Qwen2.5-32B                | 40.2          |
| SWE-RL \[Wei et al., [2025](#bib.bib31)\]                 | Llama3-70B                 | 41.0          |
| Skywork-SWE-32B \[Zeng et al., [2025](#bib.bib40)\]       | Qwen2.5-Coder-32B-Instruct | 47.9          |
| SWE-Mirror-LM-32B \[Wang et al., [2025a](#bib.bib29)\]    | Qwen2.5-Coder-32B-Instruct | 52.2          |
| SWE-Lego-32B \[Tao et al., [2026](#bib.bib25)\]           | Qwen3-32B                  | 52.6          |
| KAT-Dev-32B \[Zhan et al., [2025](#bib.bib41)\]           | \-                         | 62.4          |
| Models of the same size                                   |                            |               |
| Qwen3-30B-A3B-Instruct \[Team, [2025](#bib.bib27)\]       | \-                         | 22.0          |
| Qwen3-Coder-30B-A3B-Instruct \[Team, [2025](#bib.bib27)\] | \-                         | 51.6          |
| GLM-4.7-Flash-30A3B \[Zhipu AI, [2026](#bib.bib44)\]      | \-                         | 59.2          |
| Our Model                                                 |                            |               |
| Scale-SWE-Agent                                           | Qwen3-30B-A3B-Instruct     | 64.0          |

## 3 Experiments

### 3.1 Experiment Setup

Agent Scaffolding. We employed OpenHands \[Wang et al., [2025b](#bib.bib30)\], an open-source, event-driven platform, as the unified agent framework for all experiments. OpenHands facilitates LLM agents to iteratively edit files, execute shell commands, and browse the web within sandboxed containers. We selected this framework due to its proven ability to establish robust and reproducible baselines on benchmarks such as SWE-Bench.

Agent Post-training. We perform post-training on the Qwen3-30B-A3B-Instruct \[Team, [2025](#bib.bib27)\] base model. The training process is configured with a learning rate of 1e-5, a batch size of 128, and a warmup ratio of 0.05, supporting a maximum context length of 131,072.

Evaluation Benchmarks and MetricsOur evaluation is conducted on SWE-bench Verified \[Chowdhury et al., [2024](#bib.bib5)\], a benchmark comprising 500 high-quality, human-curated Python software issues. We report the Resolved Rate (%), representing the proportion of instances for which the model generates a correct solution. Notably, although the models were trained with a sequence length of 131,072, we extended the context limit to 262,144 during inference to handle larger inputs.

### 3.2 Experiment Results

As shown in Table [3](#S2.T3 "Table 3 ‣ 2.4 Dataset Statistics and Trajectory Distillation ‣ 2 Scale-SWE: Software Task Scaling ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"), the Scale-SWE Agent demonstrates superior performance on the SWE-bench Verified. First, regarding the impact of our scaling strategy, Scale-SWE Agent achieves a remarkable 42.0% absolute improvement over its base model, Qwen3-30B-A3B-Instruct, boosting the pass rate from 22.0% to 64.0%. Second, in comparison to models of the same size, our method significantly outperforms strong competitors, including Qwen3-Coder (51.6%) and GLM-4.7-Flash (59.2%). Furthermore, Scale-SWE Agent exhibits exceptional efficiency, surpassing models with significantly larger parameter counts, such as SWE-RL (Llama3-70B) and SWE-Fixer-72B. Notably, it also exceeds the previous state-of-the-art open-source method, KAT-Dev-32B (62.4%), and outperforms recent specialist models like SWE-Mirror and SWE-Lego by a margin of over 11%. These results validate the effectiveness of scaling up SWE-style data for enhancing software engineering capabilities.

![Refer to caption](2602.09892v4/figures/merge_traj_stat.drawio.png)

Figure 4: Comparison of distillation data statistics across different datasets. We show the probability density functions for (top) total token count and (bottom) the number of tool-call turns.

To evaluate the efficacy of our data compared to existing alternatives, we conducted controlled experiments by performing distillation and SFT on SWE-Gym and SWE-smith using an identical pipeline. As shown in Table [4](#S3.T4 "Table 4 ‣ 3.2 Experiment Results ‣ 3 Experiments ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"), Scale-SWE significantly outperforms both baselines. Notably, despite SWE-smith possessing a considerably larger volume of instances than SWE-Gym, it yields slightly inferior performance. This performance gap suggests a diminishing return on purely synthetic data and underscores a critical insight: high-fidelity, real-world data is inherently more effective than massive-scale synthetic alternatives. This finding reinforces the importance of our large-scale “real-data” construction approach.

The distributions of interaction turns and token counts are presented in Figure [4](#S3.F4 "Figure 4 ‣ 3.2 Experiment Results ‣ 3 Experiments ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery"). As illustrated in these figures, Scale-SWE tasks necessitate a greater number of turns for repository exploration and iterative debugging. This observation underscores the high complexity and difficulty inherent in the Scale-SWE dataset.

Table 4: SFT performance comparison on SWE-bench Verified. All models are fine-tuned using the same distillation pipeline to ensure a fair comparison.

| Dataset Name | SWE-bench Verified |
| ------------ | ------------------ |
| SWE-Gym      | 54.8               |
| SWE-smith    | 54.6               |
| Scale-SWE    | 64.0               |

## 4 Related Work

SWE Benchmark. Since the introduction of the prevailing software engineering benchmark, SWE-bench \[Jimenez et al., [2023](#bib.bib16)\] and SWE-bench-Verified \[Chowdhury et al., [2024](#bib.bib5)\], many other benchmarks have emerged to assess multi-modal \[Yang et al., [2024b](#bib.bib35)\], multi-language \[Zan et al., [2025b](#bib.bib39), Rashid et al., [2025](#bib.bib22), Guo et al., [2025a](#bib.bib12)\], and long-horizon capabilities \[Deng et al., [2025](#bib.bib6)\]. These new benchmarks also evaluate whole repository generation \[Ding et al., [2025](#bib.bib7)\], scientific domain knowledge \[Duston et al., [2025](#bib.bib8)\], and other specialized abilities \[Ma et al., [2025](#bib.bib18), Shetty et al., [2025](#bib.bib23)\]. Collectively, these benchmarks constitute a comprehensive evaluation ecosystem, establishing rigorous standards that assess the multifaceted capabilities required for autonomous software engineering.

SWE Datasets. High-quality data is pivotal for enhancing the programming capabilities of Large Language Models (LLMs). Recently, there has been a surge in repository-level software engineering datasets aimed at addressing complex coding tasks. Efforts to scale up SWE task instances generally fall into two categories. One line of work, including R2E-Gym \[Jain et al., [2025](#bib.bib15)\], SWE-smith \[Yang et al., [2025a](#bib.bib36)\], and SWE-Mirror \[Wang et al., [2025a](#bib.bib29)\], attempts to scale up training data through synthetic generation. Conversely, other works focus on mining real-world issues; for instance, SWE-Gym \[Pan et al., [2024](#bib.bib21)\] constructed 2,400 executable instances restricted to 11 repositories, while SWE-rebench \[Badertdinov et al., [2025](#bib.bib3)\] further expanded this collection to 7,500 executable instances.

SWE Models and Agents. Recent advancements have introduced powerful models specialized for SWE tasks, including SWE-RL \[Wei et al., [2025](#bib.bib31)\], SWE-Swiss \[He et al., [2025](#bib.bib14)\], Kimi-Dev \[Yang et al., [2025b](#bib.bib37)\], and KAT-Coder \[Zhan et al., [2025](#bib.bib41)\]. In parallel, frameworks such as SWE-agent \[Yang et al., [2024a](#bib.bib34)\], Mini-SWE-Agent \[Yang et al., [2024a](#bib.bib34)\], OpenHands \[Wang et al., [2025b](#bib.bib30)\], and MOpenHands \[Zan et al., [2025a](#bib.bib38)\] serve as effective scaffolds to streamline interactions with development environments.

## 5 Conclusion

In this work, we introduced Scale-SWE, a sandboxed multi‑agent framework that automates the construction of large‑scale, high‑quality software engineering data along with executable environments. By orchestrating specialized agents for environment setup, unit‑test generation, and task description synthesis, we processed six million real‑world pull requests to produce Scale-SWE-Data—a dataset of 100,000 instances that surpasses existing datasets in both scale and repository diversity. We further demonstrated the practical value of the dataset by distilling high‑quality trajectories and fine‑tuning Qwen3‑30B-A3B-Instruct to create Scale-SWE-Agent, which achieves substantial improvements on SWE‑Bench‑Verified—increasing the resolve rate from 22% to 64%. This advancement underscores the quality and utility of our data for training more capable code agents. We believe Scale-SWE opens new avenues for scalable SWE‑style dataset construction and provides a rich, open‑access resource to support the development of more capable LLM‑based software engineering agents. In future work, we aim to not only increase the volume of training data to fully leverage the potential of Scale-SWE-Data but also significantly broaden its linguistic scope. Specifically, we plan to extend our pipeline to support other major programming languages—such as Java, C, C++, and Rust—thereby fostering the development of truly language-agnostic software engineering agents.

## References

* Anthropic \[2025a\] Anthropic. Introducing Claude Sonnet 4.5, Sept. 2025a. URL <https://www.anthropic.com/news/claude-sonnet-4-5>.
* Anthropic \[2025b\] Anthropic. Announcing Claude Sonnet 4.5, 2025b. URL <https://www.anthropic.com/news/claude-sonnet-4-5>. Accessed: 2025-09-30.
* Badertdinov et al. \[2025\] I. Badertdinov, A. Golubev, M. Nekrashevich, A. Shevtsov, S. Karasik, A. Andriushchenko, M. Trofimova, D. Litvintseva, and B. Yangel. Swe-rebench: An automated pipeline for task collection and decontaminated evaluation of software engineering agents. _arXiv preprint arXiv:2505.20411_, 2025.
* Chen et al. \[2025\] G. Chen, Z. Qiao, X. Chen, D. Yu, H. Xu, W. X. Zhao, R. Song, W. Yin, H. Yin, L. Zhang, et al. Iterresearch: Rethinking long-horizon agents via markovian state reconstruction. _arXiv preprint arXiv:2511.07327_, 2025.
* Chowdhury et al. \[2024\] N. Chowdhury, J. Aung, C. J. Shern, O. Jaffe, D. Sherburn, G. Starace, E. Mays, R. Dias, M. Aljubeh, M. Glaese, C. E. Jimenez, J. Yang, L. Ho, T. Patwardhan, K. Liu, and A. Madry. Introducing SWE-bench verified, 2024. URL <https://openai.com/index/introducing-swe-bench-verified/>. OpenAI Blog Post.
* Deng et al. \[2025\] X. Deng, J. Da, E. Pan, Y. Y. He, C. Ide, K. Garg, N. Lauffer, A. Park, N. Pasari, C. Rane, et al. Swe-bench pro: Can ai agents solve long-horizon software engineering tasks? _arXiv preprint arXiv:2509.16941_, 2025.
* Ding et al. \[2025\] J. Ding, S. Long, C. Pu, H. Zhou, H. Gao, X. Gao, C. He, Y. Hou, F. Hu, Z. Li, et al. Nl2repo-bench: Towards long-horizon repository generation evaluation of coding agents. _arXiv preprint arXiv:2512.12730_, 2025.
* Duston et al. \[2025\] T. Duston, S. Xin, Y. Sun, D. Zan, A. Li, S. Xin, K. Shen, Y. Chen, Q. Sun, G. Zhang, et al. Ainsteinbench: Benchmarking coding agents on scientific repositories. _arXiv preprint arXiv:2512.21373_, 2025.
* Froger et al. \[2025\] R. Froger, P. Andrews, M. Bettini, A. Budhiraja, R. S. Cabral, V. Do, E. Garreau, J.-B. Gaya, H. Laurençon, M. Lecanu, et al. Are: Scaling up agent environments and evaluations. _arXiv preprint arXiv:2509.17158_, 2025.
* Golubev et al. \[2025\] A. Golubev, M. Trofimova, S. Polezhaev, I. Badertdinov, M. Nekrashevich, A. Shevtsov, S. Karasik, S. Abramov, A. Andriushchenko, F. Fisin, et al. Training long-context, multi-turn software engineering agents with reinforcement learning. _arXiv preprint arXiv:2508.03501_, 2025.
* Google \[2025\] Google. Gemini 3 pro, 2025. URL <https://deepmind.google/models/gemini/pro/>.
* Guo et al. \[2025a\] L. Guo, W. Tao, R. Jiang, Y. Wang, J. Chen, X. Liu, Y. Ma, M. Mao, H. Zhang, and Z. Zheng. Omnigirl: A multilingual and multimodal benchmark for github issue resolution. _Proceedings of the ACM on Software Engineering_, 2(ISSTA):24–46, 2025a.
* Guo et al. \[2025b\] L. Guo, Y. Wang, C. Li, P. Yang, J. Chen, W. Tao, Y. Zou, D. Tang, and Z. Zheng. Swe-factory: Your automated factory for issue resolution training data and evaluation benchmarks. _arXiv preprint arXiv:2506.10954_, 2025b. URL <https://arxiv.org/abs/2506.10954>.
* He et al. \[2025\] Z. He, Q. Yang, W. Sheng, X. Zhong, K. Zhang, C. An, W. Shi, T. Cai, D. He, J. Chen, and J. Xu. Swe-swiss: A multi-task fine-tuning and rl recipe for high-performance issue resolution, 2025. Notion Blog.
* Jain et al. \[2025\] N. Jain, J. Singh, M. Shetty, L. Zheng, K. Sen, and I. Stoica. R2e-gym: Procedural environments and hybrid verifiers for scaling open-weights swe agents. _arXiv preprint arXiv:2504.07164_, 2025.
* Jimenez et al. \[2023\] C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press, and K. Narasimhan. Swe-bench: Can language models resolve real-world github issues? _arXiv preprint arXiv:2310.06770_, 2023.
* Liu et al. \[2025\] A. Liu, A. Mei, B. Lin, B. Xue, B. Wang, B. Xu, B. Wu, B. Zhang, C. Lin, C. Dong, et al. Deepseek-v3\. 2: Pushing the frontier of open large language models. _arXiv preprint arXiv:2512.02556_, 2025.
* Ma et al. \[2025\] J. J. Ma, M. Hashemi, A. Yazdanbakhsh, K. Swersky, O. Press, E. Li, V. J. Reddi, and P. Ranganathan. Swe-fficiency: Can language models optimize real-world repositories on real workloads? _arXiv preprint arXiv:2511.06090_, 2025.
* MiniMax AI \[2025\] MiniMax AI. Multilingual and Multi-Task Coding with Strong Generalization: A Look at MiniMax-M2.1. Hugging Face Blog, 2025. URL <https://huggingface.co/blog/MiniMaxAI/multilingual-and-multi-task-coding-with-strong-gen>. Accessed: 2025-12-23.
* OpenAI \[2025\] OpenAI. Introducing GPT-5.2, Dec. 2025. URL <https://openai.com/index/introducing-gpt-5-2/>.
* Pan et al. \[2024\] J. Pan, X. Wang, G. Neubig, N. Jaitly, H. Ji, A. Suhr, and Y. Zhang. Training software engineering agents and verifiers with swe-gym. _arXiv preprint arXiv:2412.21139_, 2024.
* Rashid et al. \[2025\] M. S. Rashid, C. Bock, Y. Zhuang, A. Buchholz, T. Esler, S. Valentin, L. Franceschi, M. Wistuba, P. T. Sivaprasad, W. J. Kim, et al. Swe-polybench: A multi-language benchmark for repository level evaluation of coding agents. _arXiv preprint arXiv:2504.08703_, 2025.
* Shetty et al. \[2025\] M. Shetty, N. Jain, J. Liu, V. Kethanaboyina, K. Sen, and I. Stoica. Gso: Challenging software optimization tasks for evaluating swe-agents. _arXiv preprint arXiv:2505.23671_, 2025.
* Sonwane et al. \[2025\] A. Sonwane, I. White, H. Lee, M. Pereira, L. Caccia, M. Kim, Z. Shi, C. Singh, A. Sordoni, M.-A. Côté, et al. Bugpilot: Complex bug generation for efficient learning of swe skills. _arXiv preprint arXiv:2510.19898_, 2025.
* Tao et al. \[2026\] C. Tao, J. Chen, Y. Jiang, K. Kou, S. Wang, R. Wang, X. Li, S. Yang, Y. Du, J. Dai, et al. Swe-lego: Pushing the limits of supervised fine-tuning for software issue resolving. _arXiv preprint arXiv:2601.01426_, 2026.
* Team et al. \[2025a\] K. Team, Y. Bai, Y. Bao, G. Chen, J. Chen, N. Chen, R. Chen, Y. Chen, Y. Chen, Y. Chen, et al. Kimi k2: Open agentic intelligence. _arXiv preprint arXiv:2507.20534_, 2025a.
* Team \[2025\] Q. Team. Qwen3 technical report, 2025. URL <https://arxiv.org/abs/2505.09388>.
* Team et al. \[2025b\] T. D. Team, B. Li, B. Zhang, D. Zhang, F. Huang, G. Li, G. Chen, H. Yin, J. Wu, J. Zhou, et al. Tongyi deepresearch technical report. _arXiv preprint arXiv:2510.24701_, 2025b.
* Wang et al. \[2025a\] J. Wang, D. Zan, S. Xin, S. Liu, Y. Wu, and K. Shen. Swe-mirror: Scaling issue-resolving datasets by mirroring issues across repositories. _arXiv preprint arXiv:2509.08724_, 2025a.
* Wang et al. \[2025b\] X. Wang, S. Rosenberg, J. Michelini, C. Smith, H. Tran, E. Nyst, R. Malhotra, X. Zhou, V. Chen, R. Brennan, et al. The openhands software agent sdk: A composable and extensible foundation for production agents. _arXiv preprint arXiv:2511.03690_, 2025b.
* Wei et al. \[2025\] Y. Wei, O. Duchenne, J. Copet, Q. Carbonneaux, L. Zhang, D. Fried, G. Synnaeve, R. Singh, and S. I. Wang. Swe-rl: Advancing llm reasoning via reinforcement learning on open software evolution. _arXiv preprint arXiv:2502.18449_, 2025.
* Xiao et al. \[2026\] B. Xiao, B. Xia, B. Yang, B. Gao, B. Shen, C. Zhang, C. He, C. Lou, F. Luo, G. Wang, et al. Mimo-v2-flash technical report. _arXiv preprint arXiv:2601.02780_, 2026.
* Xie et al. \[2025\] C. Xie, B. Li, C. Gao, H. Du, W. Lam, D. Zou, and K. Chen. Swe-fixer: Training open-source llms for effective and efficient github issue resolution. _arXiv preprint arXiv:2501.05040_, 2025.
* Yang et al. \[2024a\] J. Yang, C. E. Jimenez, A. Wettig, K. Lieret, S. Yao, K. Narasimhan, and O. Press. Swe-agent: Agent-computer interfaces enable automated software engineering. _Advances in Neural Information Processing Systems_, 37:50528–50652, 2024a.
* Yang et al. \[2024b\] J. Yang, C. E. Jimenez, A. L. Zhang, K. Lieret, J. Yang, X. Wu, O. Press, N. Muennighoff, G. Synnaeve, K. R. Narasimhan, et al. Swe-bench multimodal: Do ai systems generalize to visual software domains? _arXiv preprint arXiv:2410.03859_, 2024b.
* Yang et al. \[2025a\] J. Yang, K. Lieret, C. E. Jimenez, A. Wettig, K. Khandpur, Y. Zhang, B. Hui, O. Press, L. Schmidt, and D. Yang. Swe-smith: Scaling data for software engineering agents. _arXiv preprint arXiv:2504.21798_, 2025a.
* Yang et al. \[2025b\] Z. Yang, S. Wang, K. Fu, W. He, W. Xiong, Y. Liu, Y. Miao, B. Gao, Y. Wang, Y. Ma, et al. Kimi-dev: Agentless training as skill prior for swe-agents. _arXiv preprint arXiv:2509.23045_, 2025b.
* Zan et al. \[2025a\] D. Zan, Z. Huang, W. Liu, H. Chen, L. Zhang, S. Xin, L. Chen, Q. Liu, X. Zhong, A. Li, S. Liu, Y. Xiao, L. Chen, Y. Zhang, J. Su, T. Liu, R. Long, K. Shen, and L. Xiang. Multi-swe-bench: A multilingual benchmark for issue resolving, 2025a. URL <https://arxiv.org/abs/2504.02605>.
* Zan et al. \[2025b\] D. Zan, Z. Huang, W. Liu, H. Chen, L. Zhang, S. Xin, L. Chen, Q. Liu, X. Zhong, A. Li, et al. Multi-swe-bench: A multilingual benchmark for issue resolving. _arXiv preprint arXiv:2504.02605_, 2025b.
* Zeng et al. \[2025\] L. Zeng, Y. Li, Y. Xiao, C. Li, C. Y. Liu, R. Yan, T. Wei, J. He, X. Song, Y. Liu, et al. Skywork-swe: Unveiling data scaling laws for software engineering in llms. _arXiv preprint arXiv:2506.19290_, 2025.
* Zhan et al. \[2025\] Z. Zhan, K. Deng, J. Wang, X. Zhang, H. Tang, M. Zhang, Z. Lai, H. Huang, W. Xiang, K. Wu, et al. Kat-coder technical report. _arXiv preprint arXiv:2510.18779_, 2025.
* Zhang et al. \[2025\] L. Zhang, S. He, C. Zhang, Y. Kang, B. Li, C. Xie, J. Wang, M. Wang, Y. Huang, S. Fu, et al. Swe-bench goes live! _arXiv preprint arXiv:2505.23419_, 2025.
* Zhipu AI \[2025\] Zhipu AI. GLM-4.7: Technical Blog. Zhipu AI Blog, 2025. URL <https://z.ai/blog/glm-4.7>. Accessed: 2025-12-22.
* Zhipu AI \[2026\] Zhipu AI. GLM-4.7-Flash: Model Repository. Hugging Face, 2026. URL <https://huggingface.co/zai-org/GLM-4.7-Flash>. Accessed: 2026-01-19.

## Appendix A Scale-SWE workflow details.

### A.1 Scale-SWE workflow Overview.

![Refer to caption](2602.09892v4/figures/DataEngineWorkflow.drawio.png)

Figure 5: Schematic workflow for automated Scale-SWE task synthesis. From an initial pool of 23k repositories and 6M pull requests, the pipeline utilizes LLM-as-a-judge to filter for quality and relevance. The selected 1M pull requests are then transformed into formal software engineering task instances via a sandboxed orchestration of specialized agents responsible for environment building, test creation, and statement writing.

## Appendix B Scale-SWE Task Instance Structure

The structure of a Scale-SWE task instance closely adheres to the SWE-bench standard, with a necessary adaptation to accommodate synthetic data. Specifically, since original developer-written “fail-to-pass” (F2P) tests are not available for all mined instances, we include a field for F2P scripts generated by our unit-test creator agent. A Scale-SWE task instance consists of the following fields:

- instance\_id: A unique identifier formatted as {user}\_{repo}\_pr{id}.
- user: The owner of the GitHub repository.
- repo: The name of the GitHub repository.
- language: The programming language of the codebase (currently Python).
- workdir: The working directory path within the environment.
- image\_url: The URL of the pre-built Docker image for the task.
- patch: The ground-truth patch (Golden Patch) from the corresponding pull request.
- pr\_commit: The commit hash of the pull request.
- parent\_commit: The commit hash of the parent commit (base state).
- problem\_statement: The issue description conveying the bug, provided to the model as input.
- f2p\_patch: The developer-written test patch containing tests that fail before the fix (if available).
- f2p\_script: The synthetic reproduction script generated by our unit-test creator agent (used when f2p\_patch is absent).
- FAIL\_TO\_PASS: A list of unit tests that fail when applied to the buggy version but pass after the fix.
- PASS\_TO\_PASS: A list of unit tests that pass in both the buggy and fixed versions (regression tests).
- github\_url: The URL of the original GitHub repository.
- pre\_commands: Commands executed immediately upon entering the container to revert future commit information and prevent data leakage.

## Appendix C Implementation Details

The hyperparameters for SFT are detailed in Table [5](#A3.T5 "Table 5 ‣ Appendix C Implementation Details ‣ Immersion in the GitHub Universe: Scaling Coding Agents to Mastery").

Table 5: Key hyperparameters in the SFT phase.

| Hyperparameter         | Value         |
| ---------------------- | ------------- |
| Learning Rate          | 1e-5          |
| Base model             | Qwen3-30B-A3B |
| Batch size             | 128           |
| Maximum Context Length | 131,072       |
| Warmup ratio           | 0.05          |
| LR scheduler type      | Cosine        |
| Epoch                  | 3             |

## Appendix D Anti-hack Strategy

To ensure the integrity of the SWE-bench evaluation, we implement an anti-leak strategy to prevent the LLM from accessing ground truth solutions via Git history (e.g., using commands like git log --all). The following sanitization script is executed immediately after initializing the environment container:

[⬇](data:text/plain;base64,CmdpdCBjbGVhbiAtZmQgLWUgJyouZWdnLWluZm8nIC1lICcudG94JyAtZSAnLnZlbnYnICYmIGdpdCBjaGVja291dCB7cGFyZW50X2NvbW1pdH0KTkVXX0JSQU5DSD0ic3dlX2JlbmNoX2NsZWFuX21haW4iCkNVUlJFTlRfSEVBRD0kKGdpdCByZXYtcGFyc2UgSEVBRCkKZ2l0IHN0YXNoIC1hCmdpdCBjbGVhbiAtZmQKZ2l0IHJlc2V0IC0taGFyZCAkQ1VSUkVOVF9IRUFECmdpdCBzdGFzaCBwb3AgfHwgZWNobyAiTm8gc3Rhc2ggdG8gYXBwbHkgb3IgY29uZmxpY3Qgb2NjdXJyZWQiCgpnaXQgY29uZmlnIHVzZXIuZW1haWwgInByZS1hZ2VudEBzd2FsbS5sb2NhbCIgJiYgZ2l0IGNvbmZpZyB1c2VyLm5hbWUgIlByZS1BZ2VudCIgJiYgZ2l0IGFkZCAuICYmIGdpdCBjb21taXQgLW0gInByZS1hZ2VudCBjb21taXQiCgoKQ1VSUkVOVF8zX1BSSU1FPSQoZ2l0IHJldi1wYXJzZSBIRUFEKQoKZ2l0IGZvci1lYWNoLXJlZiAtLWZvcm1hdD0iJShyZWZuYW1lKSIgcmVmcy9yZW1vdGVzLyB8IHhhcmdzIC1JIHt9IGdpdCB1cGRhdGUtcmVmIC1kIHt9CmdpdCB0YWcgLWwgfCB4YXJncyAtciBnaXQgdGFnIC1kCgpybSAtZiAuZ2l0L3BhY2tlZC1yZWZzCnJtIC1mIC5naXQvT1JJR19IRUFEIC5naXQvRkVUQ0hfSEVBRCAuZ2l0L01FUkdFX0hFQUQgLmdpdC9DSEVSUllfUElDS19IRUFEIC5naXQvcmVmcy9zdGFzaApybSAtcmYgLmdpdC9sb2dzLwoKZ2l0IHVwZGF0ZS1yZWYgcmVmcy9oZWFkcy8ke05FV19CUkFOQ0h9ICRDVVJSRU5UXzNfUFJJTUUKZ2l0IHN5bWJvbGljLXJlZiBIRUFEIHJlZnMvaGVhZHMvJHtORVdfQlJBTkNIfQoKZ2l0IGZvci1lYWNoLXJlZiAtLWZvcm1hdD0iJShyZWZuYW1lKSIgcmVmcy9oZWFkcy8gfCBncmVwIC12ICJyZWZzL2hlYWRzLyR7TkVXX0JSQU5DSH0iIHwgeGFyZ3MgLUkge30gZ2l0IHVwZGF0ZS1yZWYgLWQge30KCmdpdCBnYyAtLXBydW5lPW5vdyAtLWFnZ3Jlc3NpdmU=)

1

2git clean \-fd \-e ’\*.egg-info’ \-e ’.tox’ \-e ’.venv’ && git checkout {parent\_commit}

3NEW\_BRANCH\="swe\_bench\_clean\_main"

4CURRENT\_HEAD\=$(git rev\-parse HEAD)

5git stash \-a

6git clean \-fd

7git reset \--hard $CURRENT\_HEAD

8git stash pop || echo "No␣stash␣to␣apply␣or␣conflict␣occurred"

9

10git config user.email "pre-agent@swalm.local" && git config user.name "Pre-Agent" && git add . && git commit \-m "pre-agent␣commit"

11

12

13CURRENT\_3\_PRIME\=$(git rev\-parse HEAD)

14

15git for\-each\-ref \--format\="%(refname)" refs/remotes/ | xargs \-I {} git update\-ref \-d {}

16git tag \-l | xargs \-r git tag \-d

17

18rm \-f .git/packed\-refs

19rm \-f .git/ORIG\_HEAD .git/FETCH\_HEAD .git/MERGE\_HEAD .git/CHERRY\_PICK\_HEAD .git/refs/stash

20rm \-rf .git/logs/

21

22git update\-ref refs/heads/${NEW\_BRANCH} $CURRENT\_3\_PRIME

23git symbolic\-ref HEAD refs/heads/${NEW\_BRANCH}

24

25git for\-each\-ref \--format\="%(refname)" refs/heads/ | grep \-v "refs/heads/${NEW\_BRANCH}" | xargs \-I {} git update\-ref \-d {}

26

27git gc \--prune\=now \--aggressive

## Appendix E Prompts in Scale-SWE workflow

- Repository filtering prompt
- Pull request filtering prompt
- Environment builder agent prompt
- Unit-test creator agent prompt
- Problem statement writer prompt
- Bug type categorization prompt
