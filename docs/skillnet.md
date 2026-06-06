# [ ](#create-evaluate-and-connect-ai-skills--skillnet-a-large-scale-agentic-skill-graph-knowledge-base)  Create, Evaluate, and Connect AI Skills | SkillNet: A Large-Scale Agentic "Skill Graph" Knowledge Base

[ Community Article](https://huggingface.co/blog/xzwnlp/skillnet/blog/community) Published February 28, 2026

[  Upvote 13 ](https://huggingface.co/blog/xzwnlp/skillnet/login?next=%2Fblog%2Fxzwnlp%2Fskillnet)
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/3c7ecc398fbf851acd2a132e947a92be.svg)](/XinXuNLPer "XinXuNLPer")
* [![](https://cdn-avatars.huggingface.co/v1/production/uploads/61cd4b833dd34ba1985e0753/BfHfrwotoMESpXZOHiIe4.png)](https://huggingface.co/blog/xzwnlp/skillnet/dongguanting "dongguanting")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/e0fccbb2577d76088e09f054c35cffbc.svg)](/Ningyu "Ningyu")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/15720cf8cd69a7fecfc749f5524c2500.svg)](/hiepnh "hiepnh")
* [![](https://cdn-avatars.huggingface.co/v1/production/uploads/noauth/sD-O8vQb5mvg0ClTudZiS.jpeg)](https://huggingface.co/blog/xzwnlp/skillnet/SupreCyk "SupreCyk")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/3a8343908fbb163b711ec67d2d3b928e.svg)](/AstoneNg "AstoneNg")
* +7

[![Yuan Liang's avatar](https://huggingface.co/blog/xzwnlp/skillnet/avatars/20d2501eba3213211c46b9a1da3c9590.svg)](/LingeringYuan)

[Yuan Liang LingeringYuan Follow ](https://huggingface.co/blog/xzwnlp/skillnet/LingeringYuan)

[![Ningyu Zhang's avatar](https://huggingface.co/blog/xzwnlp/skillnet/avatars/e0fccbb2577d76088e09f054c35cffbc.svg)](/Ningyu)

[Ningyu Zhang Ningyu Follow ](https://huggingface.co/blog/xzwnlp/skillnet/Ningyu)

[![Xu Ziwen's avatar](https://huggingface.co/blog/xzwnlp/skillnet/avatars/5aea69671eb1299aaaa948d888b4b64f.svg)](/xzwnlp)

[Xu Ziwen xzwnlp Follow ](https://huggingface.co/blog/xzwnlp/skillnet/xzwnlp)

> * [Introduction](#introduction "Introduction")
> * [1\. SkillNet: Empowering Agents to Master and Deploy Skills](#1-skillnet-empowering-agents-to-master-and-deploy-skills "1. SkillNet: Empowering Agents to Master and Deploy Skills")
> * [2\. Skill Ontology: Building a Skill Knowledge Network](#2-skill-ontology-building-a-skill-knowledge-network "2. Skill Ontology: Building a Skill Knowledge Network")
> * [3\. Construction and Evaluation of SkillNet](#3-construction-and-evaluation-of-skillnet "3. Construction and Evaluation of SkillNet")
>   * [Multi-source Data Collection](#multi-source-data-collection "Multi-source Data Collection")
>   * [Automated Construction Pipeline](#automated-construction-pipeline "Automated Construction Pipeline")
>   * [Multi-dimensional Quality Evaluation](#multi-dimensional-quality-evaluation "Multi-dimensional Quality Evaluation")
> * [4\. Practical Applications of SkillNet](#4-practical-applications-of-skillnet "4. Practical Applications of SkillNet")
>   * [⚡ Get Started with SkillNet in 3 Minutes](#⚡-get-started-with-skillnet-in-3-minutes "⚡ Get Started with SkillNet in 3 Minutes")
>   * [OpenClaw Integration](#openclaw-integration "OpenClaw Integration")
> * [5\. Enhancing Agents with SkillNet](#5-enhancing-agents-with-skillnet "5. Enhancing Agents with SkillNet")
>   * [Acquiring Skill Resources to Improve Task Performance](#acquiring-skill-resources-to-improve-task-performance "Acquiring Skill Resources to Improve Task Performance")
>   * [Automatically Constructing Capability Networks and Accumulating Industry Knowledge Assets](#automatically-constructing-capability-networks-and-accumulating-industry-knowledge-assets "Automatically Constructing Capability Networks and Accumulating Industry Knowledge Assets")
> * [6\. Outlook: Reconstructing Knowledge Engineering in the Agent Era](#6-outlook-reconstructing-knowledge-engineering-in-the-agent-era "6. Outlook: Reconstructing Knowledge Engineering in the Agent Era")
>   * [Skill Evolution in the Open World](#skill-evolution-in-the-open-world "Skill Evolution in the Open World")
>   * [Synergy Between Models and Skills](#synergy-between-models-and-skills "Synergy Between Models and Skills")
>   * [Multi-Agent Collaboration and Knowledge Sharing](#multi-agent-collaboration-and-knowledge-sharing "Multi-Agent Collaboration and Knowledge Sharing")
>
> This article is also available in Chinese [简体中文](https://huggingface.co/blog/xzwnlp/skillnet-zh).

## [ ](#introduction)  Introduction

Currently, AI agents are capable of flexibly invoking tools and planning complex tasks, but the continuous evolution of their capabilities depends on the accumulation and transfer of Agentic Skills. Due to the lack of a systematic mechanism for skill accumulation and sharing, agents still have to learn from scratch through trial and error in different environments, repeatedly falling into the same pitfalls even when similar problems have long been solved. While general foundation models provide basic capabilities, they have not formed domain-specific, reusable skill structures, causing each agent to repeatedly build similar experiences in isolated contexts.

**SkillNet** is a large-scale agentic skill knowledge base built precisely to break this dilemma. It consolidates scattered practical experiences into a structured skill knowledge network that is computable, retrievable, and composable. In this way, agents can navigate specific domain knowledge like consulting a map—understanding what professional knowledge is needed, what specialized tools to use, and what skill pathways to follow—thereby enabling efficient skill sharing and rapid transfer. Preliminary experimental results show that incorporating relevant skills from SkillNet achieves performance improvements of approximately 10-30 percentage points on common benchmarks such as ALFWorld, WebShop, and ScienceWorld.

Currently, **SkillNet covers multiple domains including science, engineering, and creation, containing over 200,000 skills, from which more than 150,000 high-quality skill nodes have been curated.** This release not only provides full downloads of the skill resources but also introduces a ready-to-use **Python library**, supporting researchers and developers in rapid integration and experimentation. You are welcome to use it via `pip install skillnet-ai`.

> **SkillNet Official Homepage**: <http://skillnet.openkg.cn/>
> **SkillNet Repository**: <https://github.com/zjunlp/SkillNet>

[![overview](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/LChW_-FKppXeVv0Nan9b3.png)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/LChW%5F-FKppXeVv0Nan9b3.png)

---

## [ ](#1-skillnet-empowering-agents-to-master-and-deploy-skills)  1\. SkillNet: Empowering Agents to Master and Deploy Skills

The history of AI development is essentially a history of exploring the representation, understanding, and utilization of knowledge. This process can be divided into three stages:

1. **Textual Knowledge**: Knowledge exists as unstructured text with broad coverage but ambiguous semantics, making it difficult for machines to understand directly, thus creating a "semantic gap."
2. **Symbolic Knowledge**: Through symbolic representations like knowledge graphs and descriptive logic, knowledge is endowed with precise semantics to support rigorous reasoning. However, the high cost of knowledge acquisition makes it difficult to apply at scale.
3. **Vectorized Knowledge**: Large language models encode knowledge in high-dimensional vector spaces, offering strong generalization and convenient invocation. However, they suffer from a lack of interpretability, uncontrollable processes, and fragile factual consistency, leading to unstable performance in high-reliability tasks.

The three forms mentioned above focus on describing "what the world is" (Know What) but lack an effective representation of procedural knowledge on "how to do it" (Know How). This is exactly the core dilemma current agents face when tackling complex tasks.

To break through this bottleneck, we propose an engineering approach to shift from static knowledge to dynamic "Skill Knowledge." Simply put, a **Skill** is a procedural knowledge unit that encapsulates specific intentions, can be parameterized for invocation, and produces deterministic outputs. It integrates the contextual knowledge, action steps, and historical experience required to guide the agent in completing tasks correctly, specifically including the following core elements:

* **Applicable Scenarios**: Defines prerequisites, constraints, and failure scenarios.
* **Tools and Interfaces**: Declares required external resources and dependencies.
* **Reasoning Structure**: Solidifies verified decision chains and operational sequences.
* **Metacognitive Information**: Records evaluation metrics such as success rates, resource consumption, and execution latency.

A skill is not only executable knowledge but also a measurable, reusable, and evolvable capability component. It is this modular representation that allows agents to efficiently combine and flexibly transfer capabilities based on an existing library, thoroughly freeing them from the trial-and-error trap. This achieves true mastery and deployment of skills, laying a crucial foundational stone for building more general and robust AI systems.

---

## [ ](#2-skill-ontology-building-a-skill-knowledge-network)  2\. Skill Ontology: Building a Skill Knowledge Network

SkillNet is not a simple accumulation of skills but a structured skill network. We propose the **Skill Ontology** to characterize the systematic organizational relationships between skills, divided into a three-layer structure:

[![ontology](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/jbVXlRMZS_t47aYzMJESN.png)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/jbVXlRMZS%5Ft47aYzMJESN.png)

* **Layer 1: Taxonomy** — Organizes skills by function and abstraction level.
* **Layer 2: Relational Layer** — Characterizes relationships such as dependency, composition, and similarity/substitution between skills, providing structural support for workflow planning.
* **Layer 3: Skill Package Layer** — Specific skills exist as locally deployable packages, connecting to the upper network through dependency relationships.

Through relationships such as **compose, belong\_to, depend\_on, and similar\_to**, SkillNet not only characterizes the static associations between skills but also forms a dynamic ontology that continuously updates with experience, building a capability space that is reason-able, plannable, and evolvable. In this capability space, skill relationships are continuously revised and expanded according to task distributions, execution feedback, and environmental changes. Agents can "assemble" capabilities like an engineering system: selecting appropriate modules, combining them on demand, avoiding known failure modes, and rapidly iterating in real-world tasks.

Essentially, SkillNet transforms "knowledge" from static storage into an executable capability toolbox. This not only enhances the credibility and controllability of agents in complex tasks but also provides a maintainable, scalable, and evolvable capability foundation for long-term online agents, cross-domain collaboration, and scientific automation.

---

## [ ](#3-construction-and-evaluation-of-skillnet)  3\. Construction and Evaluation of SkillNet

[![pipeline](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/1xezrioYZe4G-l5IRsBN-.png)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/1xezrioYZe4G-l5IRsBN-.png)

### [ ](#multi-source-data-collection)  Multi-source Data Collection

The construction of SkillNet is based on large-scale, multi-source skill data collection. We systematically gather skills from the following channels:

* **Existing Skills on the Web**: Integrating verified skill implementations from the open-source community.
* **Implemented Academic Datasets**: Extracting standardized methods and workflows from academic datasets across various domains.
* **GitHub Repositories**: Mining reusable capability modules from real-world projects.
* **Agent Execution Trajectories**: Automatically extracting skills from the execution traces of our autonomously running agents.

### [ ](#automated-construction-pipeline)  Automated Construction Pipeline

Building on data collection, we propose an automated pipeline to transform multi-source heterogeneous data into structured, reusable skill representations. This process first systematically explores the task space to collect complete behavioral trajectories encompassing both successes and failures; then, it automatically induces and decomposes the multi-step decision-making process, abstracting modular Skills with clear semantic boundaries and interface definitions. Furthermore, combining the reasoning capabilities and rule constraints of LLMs, it automatically constructs hierarchical, dependency, and compositional relationships between skills, thereby forming a structured and evolvable skill relationship network.

### [ ](#multi-dimensional-quality-evaluation)  Multi-dimensional Quality Evaluation

The evaluation mechanism is key to SkillNet's reliable operation. To prevent skills from being unstable or uncontrollable during real-world execution, SkillNet proposes a systematic multi-dimensional evaluation of skill quality, including key metrics such as: **Safety, Completeness, Executability, Maintainability, and Cost-Awareness**.

---

## [ ](#4-practical-applications-of-skillnet)  4\. Practical Applications of SkillNet

Currently, SkillNet has completed large-scale construction across multiple domains including scientific research, engineering practice, and content creation. It has accumulated **over 200,000 candidate skills** and filtered out **more than 150,000 high-quality skill nodes** through automated quality evaluation, forming a capability network with clear semantic structures and dependency relationships.

This release also provides the accompanying **Python library** (`pip install skillnet-ai`), supporting the loading, composition, evaluation, and execution of skills. This offers infrastructure support for researchers and developers to conduct rapid integration and reproducible experiments across different agent frameworks.

Taking scientific skills as an example, SkillNet covers the complete research workflow from literature retrieval, hypothesis generation, and experimental design to result analysis and failure attribution. It transforms procedural knowledge and strategic decisions implicitly hidden in expert experience into explicit, reusable, and composable capability structures. This not only lowers the barrier to executing complex scientific tasks but also provides a new pathway for building scientific agents with planning, reflection, and continuous improvement capabilities, empowering **AI for Science**.

[![science demo](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/wwejWXJG-polI28ggT5iy.gif)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/wwejWXJG-polI28ggT5iy.gif)

Below, we introduce the usage of SkillNet using the Python package as an example. For detailed documentation, please refer to our GitHub.

### [ ](#⚡-get-started-with-skillnet-in-3-minutes)  ⚡ Get Started with SkillNet in 3 Minutes

```bash
# installation
$ pip install skillnet-ai

```

```python
from skillnet_ai import SkillNetClient
client = SkillNetClient(api_key="sk-xxx")

# search skills
skills = client.search(q="bioinformatics pipeline")

# download and apply
local_path = client.download(url=skills[0].skill_url, target_dir="./my_skills")
print(f"Skill successfully installed at: {local_path}")

# create skills
created_paths = client.create(github_url="https://github.com/openai/openai-python", output_dir="./my_skills", model="gpt-4o" )

# evaluate skills
result = client.evaluate(target="https://github.com/K-Dense-AI/claude-scientific-skills/tree/main/scientific-skills/biopython", model="gpt-4o")
print(f"Evaluation Result: {result}")

# analyze skill relations
relations = client.analyze(skills_dir="./my_skills", save_to_file=True, model="gpt-5")
for rel in relations:
    print(f"{rel['source']} --[{rel['type']}]--> {rel['target']}")

```

### [ ](#openclaw-integration)  OpenClaw Integration

[![openclaw-skillnet demo](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/iisgD9KQ_svfUQdZ098oH.gif)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/iisgD9KQ%5FsvfUQdZ098oH.gif)

SkillNet integrates with [OpenClaw](https://github.com/openclaw/openclaw) as a built-in, lazy-loaded skill ([Usage](https://github.com/zjunlp/SkillNet/tree/main?tab=readme-ov-file#-openclaw-integration)). Once installed, your agent automatically:

* **Searches** existing skills before starting complex tasks.
* **Creates** new skills from repos, documents, or completed work.
* **Evaluates & analyzes** your local library for quality and inter-skill relationships.

> Community skills guide execution → successful outcomes become new skills → periodic analysis keeps the library clean.

## [ ](#5-enhancing-agents-with-skillnet)  5\. Enhancing Agents with SkillNet

### [ ](#acquiring-skill-resources-to-improve-task-performance)  Acquiring Skill Resources to Improve Task Performance

SkillNet provides a high-quality collection of skills that have undergone deduplication, filtering, and quality evaluation, ensuring reliability at the source. We conducted experiments on multiple benchmark datasets. To prevent data leakage, the test sets were strictly excluded when constructing skill trajectories, and the relevant data has been open-sourced. In public benchmark experiments, introducing relevant skills from SkillNet improved agent performance in environments such as ALFWorld, WebShop, and ScienceWorld by approximately 10–30 percentage points.

[![result](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/1WHDERrpBCBPH2Cy0VtL3.png)](https://cdn-uploads.huggingface.co/production/uploads/6549caee44e75a7de4fee2fa/1WHDERrpBCBPH2Cy0VtL3.png)

This demonstrates that abstracting capabilities into reusable skill modules genuinely improves task success rates, rather than relying on luck through repeated prompt engineering. More importantly, the experience from every real-world task can be consolidated into standardized capability components, ready for direct invocation next time, rather than being discarded and started from scratch.

### [ ](#automatically-constructing-capability-networks-and-accumulating-industry-knowledge-assets)  Automatically Constructing Capability Networks and Accumulating Industry Knowledge Assets

SkillNet provides not only a collection of skills but also a structured linkage mechanism between them. It forms a capability network by automatically constructing relationships such as "compose, depend\_on, belong\_to, and similar\_to."

The value brought by this mechanism is direct: practices originally scattered across project code, documentation, and personal experience can be organized into a structured capability network, becoming truly queryable and reusable "industry knowledge." Enterprises can continuously accumulate business capabilities, gradually forming a capability asset library for direct reuse across different projects and teams.

## [ ](#6-outlook-reconstructing-knowledge-engineering-in-the-agent-era)  6\. Outlook: Reconstructing Knowledge Engineering in the Agent Era

The SkillNet we are releasing is a large-scale skill knowledge network tailored for agents. However, we are well aware that the current work is still in its preliminary exploration stage, and there is a long way to go before building a truly general and robust skill network. We look forward to collaborating with academia, industry, and the open-source community to drive continuous iteration and improvement in this direction. The following areas are particularly worth exploring in depth:

### [ ](#skill-evolution-in-the-open-world)  Skill Evolution in the Open World

In an open world, achieving automatic discovery, abstraction, and cross-domain transfer of skills remains challenging. In domains like industrial manufacturing, finance, and science, this involves the dynamic composition and optimization of complex tasks. Combining skill evolution mechanisms with online feedback, causal reasoning, and uncertainty modeling is expected to improve the reliability of skill selection.

### [ ](#synergy-between-models-and-skills)  Synergy Between Models and Skills

Although SkillNet provides large-scale executable skills for agents, its synergy with underlying model capabilities remains to be explored. In particular, how to use neuro-symbolic integration and memory mechanisms so that the skill structure reversely guides the model's decision-making paths, and how to dynamically reconstruct skill hierarchies and dependencies as model capabilities change, remain core issues worthy of systematic research.

### [ ](#multi-agent-collaboration-and-knowledge-sharing)  Multi-Agent Collaboration and Knowledge Sharing

In multi-agent collaborative environments, SkillNet has the potential to serve as a shared capability representation and exchange layer, supporting collaborative planning, knowledge transfer, and experience accumulation among multiple agents. We look forward to seeing SkillNet play a role in broader collaborative scenarios.

We sincerely hope that SkillNet can provide useful reference and support for building maintainable, scalable, and evolvable agent systems. We warmly welcome critique, feedback, and collaborative contributions from the community.

👉 For More Details:<https://github.com/zjunlp/SkillNet>

More from this author

[ 让大模型真正「记住你」｜LightMem：轻量高效的记忆增强生成框架 ![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/5aea69671eb1299aaaa948d888b4b64f.svg)  1 March 1, 2026 ](/blog/xzwnlp/lightmem-zh)

[ Making LLMs Truly Remember You | LightMem: Lightweight and Efficient Memory-Augmented Generation ![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/5aea69671eb1299aaaa948d888b4b64f.svg)  4 February 28, 2026 ](/blog/xzwnlp/lightmem)

### Community

EditPreview

Upload images, audio, and videos by dragging in the text input, pasting, or clicking here.

Tap or paste here to upload images

 Comment

· [Sign up](https://huggingface.co/blog/xzwnlp/skillnet/join?next=%2Fblog%2Fxzwnlp%2Fskillnet) or [log in](https://huggingface.co/blog/xzwnlp/skillnet/login?next=%2Fblog%2Fxzwnlp%2Fskillnet) to comment

[  Upvote 13 ](https://huggingface.co/blog/xzwnlp/skillnet/login?next=%2Fblog%2Fxzwnlp%2Fskillnet)
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/3c7ecc398fbf851acd2a132e947a92be.svg)](/XinXuNLPer "XinXuNLPer")
* [![](https://cdn-avatars.huggingface.co/v1/production/uploads/61cd4b833dd34ba1985e0753/BfHfrwotoMESpXZOHiIe4.png)](https://huggingface.co/blog/xzwnlp/skillnet/dongguanting "dongguanting")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/e0fccbb2577d76088e09f054c35cffbc.svg)](/Ningyu "Ningyu")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/15720cf8cd69a7fecfc749f5524c2500.svg)](/hiepnh "hiepnh")
* [![](https://cdn-avatars.huggingface.co/v1/production/uploads/noauth/sD-O8vQb5mvg0ClTudZiS.jpeg)](https://huggingface.co/blog/xzwnlp/skillnet/SupreCyk "SupreCyk")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/3a8343908fbb163b711ec67d2d3b928e.svg)](/AstoneNg "AstoneNg")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/9469599b176034548042922c0afa7051.svg)](/dark-pen "dark-pen")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/5aea69671eb1299aaaa948d888b4b64f.svg)](/xzwnlp "xzwnlp")
* [![](https://cdn-avatars.huggingface.co/v1/production/uploads/660a25825a3d57c6c5eb57d7/LUC2-egzwaNuGuW-do33N.png)](https://huggingface.co/blog/xzwnlp/skillnet/yedi-hu "yedi-hu")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/5f3078f197010ca06324d563d373ad02.svg)](/SkyMind "SkyMind")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/2f1d732c4d9df4f5b554268ee1949dda.svg)](/Xubqpanda "Xubqpanda")
* [![](https://huggingface.co/blog/xzwnlp/skillnet/avatars/d18f50100b72d3e214d0913681518caa.svg)](/amaverickid "amaverickid")
* +1

 System theme

Company

[TOS](https://huggingface.co/blog/xzwnlp/skillnet/terms-of-service) [Privacy](https://huggingface.co/blog/xzwnlp/skillnet/privacy) [About](https://huggingface.co/blog/xzwnlp/skillnet/huggingface) [Careers](https://apply.workable.com/huggingface/)

Website

[Models](https://huggingface.co/blog/xzwnlp/skillnet/models) [Datasets](https://huggingface.co/blog/xzwnlp/skillnet/datasets) [Spaces](https://huggingface.co/blog/xzwnlp/skillnet/spaces) [Pricing](https://huggingface.co/blog/xzwnlp/skillnet/pricing) [Docs](https://huggingface.co/blog/xzwnlp/skillnet/docs)
