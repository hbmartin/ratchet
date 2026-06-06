# IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents

Seoyoung Lee [leesy3891@gmail.com](mailto:leesy3891@gmail.com) , Seobin Yoon [binsong2@sookmyung.ac.kr](mailto:binsong2@sookmyung.ac.kr) , Seongbeen Lee [seongbeen@sookmyung.ac.kr](mailto:seongbeen@sookmyung.ac.kr) , Yoojung Chun [yj.chun@sookmyung.ac.kr](mailto:yj.chun@sookmyung.ac.kr) , Dayoung Park [pdysicist@sookmyung.ac.kr](mailto:pdysicist@sookmyung.ac.kr) , Doyeon Kim [ehdus@sookmyung.ac.kr](mailto:ehdus@sookmyung.ac.kr)  and Joo Yong Sim [jysim@sookmyung.ac.kr](mailto:jysim@sookmyung.ac.kr)

## Abstract

Computer-use agents operate over long horizons under noisy perception, multi-window contexts, evolving environment states. Existing approaches, from RL-based planners to trajectory retrieval, often drift from user intent and repeatedly solve routine subproblems, leading to error accumulation and inefficiency.

We present IntentCUA, a multi-agent computer-use framework designed to stabilize long-horizon execution through intent-aligned plan memory. A Planner, Plan-Optimizer, and Critic coordinate over shared memory that abstracts raw interaction traces into multi-view intent representations and reusable skills. At runtime, intent prototypes retrieve subgroup-aligned skills and inject them into partial plans, reducing redundant re-planning and mitigating error propagation across desktop applications.

In end-to-end evaluations, IntentCUA achieved a 74.83% task success rate with a Step Efficiency Ratio of 0.91, outperforming RL-based and trajectory-centric baselines. Ablations show that multi-view intent abstraction and shared plan memory jointly improve execution stability, with the cooperative multi-agent loop providing the largest gains on long-horizon tasks. These results highlight that system-level intent abstraction and memory-grounded coordination are key to reliable and efficient desktop automation in large, dynamic environments.

###### Key words and phrases:

Computer-use agents, Long-horizon automation, Noisy perception, Multi-window context, Multi Agent Planning

###### doi:

BRAG3288

## 1\. Introduction

![Refer to caption](2602.17049v2/figures/figure1.png)

Figure 1\. Overview of IntentCUA. _Offline:_ raw user traces are multi-view labeled, embedded into a shared intent space, and clustered into intent groups (IG) and subgroups (SG); SG action patterns are converted into parameterized skill schemas (“skill hints”) and stored with their SG in the IG/SG index, while plan memory stores only user-approved global plans (G). _Online:_ the Planner/Plan-Optimizer/Critic query and reuse skills; cache-first reuse and template-based gap filling reduce re-planning on long-horizon desktop tasks.

Rule-based macros and RPA systems enabled early forms of computer-use automation. However, they lack adaptability tripathi2018learning; krosnick2022parammacros when compared to recent GUI agents powered by large language models (LLMs) that can interpret screens and generate actions dynamically.

Research on GUI agents has rapidly expanded, spanning web, mobile, and increasingly desktop environments zhang2025largelanguagemodelbrainedgui; sager2025comprehensivesurveyagentscomputer. As highlighted by Tang et al. tang2025surveymllmbasedguiagents, automation across all desktop environments remains particularly challenging due to multi-window operations, OS-level shortcuts and APIs, and the need to adapt to frequent updates and complex software ecosystems. Within such environments, achieving robust long-horizon planning and managing multi-context workflows emerge as central challenges that current systems have yet to overcome.

Recent multi-modal agents attempt to address these challenges by perceiving screens and generating actions with large models anthropic2024computeruse; yang2023mm. However, robust long-horizon automation across heterogeneous desktop applications remains unresolved sager2025ai; tang2025surveymllmbasedguiagents. We identify two recurring failure modes: (i) plans spanning multiple substeps often drift from the original intent and redundantly re-solve already completed routines redis2024skill; rebmann2024recognizing, (ii) local perception errors accumulate and lead to cascading retries zhang2024dynamic; lu2024omniparser; li2024ferret; hong2024cogagent. These factors collectively hinder robust long-horizon planning, as agents frequently fall into inefficient and repetitive re-planning cycles. Actions are often retried or nullified when context drifts, leading to prolonged latency and unstable completion rates.

To address these limitations, we bridge user interaction and multi-agent planning. Rather than simply replaying trajectories or storing textual reflections shinn2024reflexion, we transform interaction traces into labeled units, induce generalized skills from sub-intent clusters, and learn multi-view representations across environment, action, keyword, and description.

These skills are organized hierarchically in a plan memory and retrieved via semantic search during planning, which supports cross-application transfer and helps stabilize long roll-outs. At runtime, intent prototypes are projected into a shared embedding space, where centroid-based retrieval augments partial plans with relevant skills.

In end-to-end evaluations, IntentCUA achieves a 74.83% task success rate with a Step Efficiency Ratio (SER) of 0.91, outperforming both RL-based (UI-TARS-1.5 ui-tars-15-seed) and trajectory-centric (UFO2 zhang2025ufo2) baselines in success rate, efficiency, and latency. Ablation studies confirm that multi-view intent abstraction and shared plan memory jointly improve execution stability, with the cooperative multi-agent loop providing the largest gains on long-horizon tasks. These results indicate that system-level intent abstraction and memory-grounded coordination are central to reliable desktop automation.

Our contributions are summarized as follows:

1. (1)
We propose IntentCUA, a multi-agent computer-use framework that stabilizes long-horizon execution through intent-aligned plan memory and coordinated planning.
2. (2)
We introduce a trace-to-skill abstraction pipeline that learns multi-view intent representations and induces hierarchical, reusable skills from raw user interaction traces.
3. (3)
We design a planning-time memory mechanism that retrieves subgroup-aligned skills to augment partial plans, reducing intent drift and redundant re-planning in dynamic desktop environments.
4. (4)
We demonstrate through extensive ablations and end-to-end evaluations that intent abstraction and memory-grounded coordination significantly improve execution stability, efficiency (SER 0.91), and task success (74.83%) on complex desktop workflows.

In summary, IntentCUA shows that intent-level abstraction and memory-grounded multi-agent coordination are key to stabilizing long-horizon desktop automation in large, dynamic environments. This automation is made possible by a robust planning policy that maintains coherence and efficiency across extended sequences.

## 2\. Related Work

### 2.1\. Desktop and GUI Automation Agents

GUI automation spans web, mobile, and desktop domains. Web agents such as WebArena and WebVoyager operate under structured DOM feedback zhou2023webarena; he2024webvoyager, but real desktop environments lack such schema-level constraints and require cross-application coordination.

Desktop benchmarks like OSWorld xie2024osworldbenchmarkingmultimodalagents tasks are typically long-horizon, requiring stable execution 10–20 sequential steps. This makes execution latency-sensitive and error-prone. As step count increases, local perception errors compound and agents often enter loops of repeated or failed actions.

Recent desktop agents such as UI-TARS qin2025ui, UFO zhang2024ufo, ScreenAgent niu2024screenagent extend vision-language models with planner–critic loops. However, surveys highlight a persistent challenge: determining actions that align with specific user contexts and preferences in dynamic, interruption-prone interfaces tang2025surveymllmbasedguiagents. Even with improved GUI grounding lu2024omniparser; hong2024cogagent; jiang2025iluvui, intent drift and redundant re-planning remain common in long-horizon workflows.

These findings indicate that stable long-horizon planning, rather than perception alone, remains the key bottleneck for reliable desktop automation.

### 2.2\. Agents Leveraging Interaction Traces

One approach to addressing long-horizon instability is to learn directly from large-scale interaction traces.

Macro-mining and process-mining techniques cluster demonstrations into recurrent procedures or labeled schemas huang2024automatic; fani2023llms; choi2022enabling. Large-scale corpora such as OS-ATLAS support perception pretraining across millions of GUI elements wu2025osatlas. Offline reinforcement learning has also been explored for device agents song2023navigating, while systems such as AppAgentv2 li2025appagentv2advancedagent, AgentBank song2024agentbank, and UI-TARS-1.5 ui-tars-15-seed leverage hierarchical feedback or large-scale trajectory tuning to improve control robustness.

These works demonstrate that interaction traces improve policy generalization and low-level stability. However, most approaches operate at the trajectory or action level, emphasizing replay or large-scale tuning rather than structured intent abstraction. As a result, redundancy and error accumulation often persist in long-horizon execution redis2024skill, and reliance on controlled environments or explicit reward signals limits applicability to open-ended desktop workflows sager2025comprehensivesurveyagentscomputer.

### 2.3\. Plan Memory, Intent Identification, and Skill Abstraction

A complementary direction enhances robustness through memory retrieval and skill abstraction.

Memory-based methods such as Reflexion shinn2024reflexion, Conversational Memory wang2023conversational, and Contextual Experience Replay cer2025 retrieve prior trajectories, manuals, or reflections to guide future decisions cai2023low. Skill-level prompting approaches such as SkillAct liu2024skillact show that abstracted routines can improve interactive performance, while UFO2 zhang2025ufo2 manages app-specific demonstrations as reusable references.

Parallel work investigates intent recognition from UI logs rebmann2024recognizing; li2020mapping and representation learning of screens (e.g., Screen2Vec li2021screen2vec, Aria-UI yang2024aria), while GUI grounding methods reduce perceptual ambiguity lu2024omniparser; li2024ferret. More recent systems explore adaptive planning and dependency modeling from demonstrations zhang2024dynamicplanningGUI; yin2025cognitivedependencies.

Despite these advances, structured and hierarchical skill abstractions that remain transferable across heterogeneous desktop workflows are still relatively underexplored. As a result, maintaining stable long-horizon execution under dynamic user contexts continues to be an active area of research. Our approach complements these directions by learning multi-view intent representations that integrate environment, action, and description signals. Skills are stored as hierarchical intent prototypes in plan memory and retrieved to augment partial plans, supporting stable long-horizon execution song2024visiontasker; gao2023assistgui.

## 3\. Intent-level Representation Learning & Skill Abstraction

### 3.1\. Intent-level Representation Learning

In this section, we describe how raw user traces are transformed into unified intent-level representations that can be clustered and later abstracted into reusable skills.

![Refer to caption](2602.17049v2/figures/figure2.png)

Figure 2\. Multi-view intent representation. Control traces use \[E,A,D\], browsing traces \[E,K,D\]. A multi-view encoder aligns views into a shared space, inducing environment-centric IG and finer SG. SG centroids enable retrieval, and SG action patterns are converted into parameterized skill schemas (“skill hints”) with verb–argument structure for planning.

As shown in Figure [2](#S3.F2 "Figure 2 ‣ 3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), each user trace is first labeled across four views: environment (EE with instances eie\_{i}), action (AA with instances aia\_{i}), keyword (KK with instances kik\_{i}), and description (DD with instances did\_{i}), where ii indexes the sequential intent units that together compose a user’s interaction trace. Each view v∈{E,A,K,D}v\\in\\{E,A,K,D\\} is represented as an embedded textual vector, capturing its semantic content. Control traces produce intent units, uiu\_{i}, of the form \[ei,ai,di\]\[e\_{i},a\_{i},d\_{i}\], while browsing traces yield \[ei,ki,di\]\[e\_{i},k\_{i},d\_{i}\]. Formally, let xi(v)x\_{i}^{(v)} denote the feature representation of intent unit uiu\_{i} in view v∈{E,A,K,D}v\\in\\{E,A,K,D\\}. A multi-view encoder ϕ​(x(v))\\phi(x^{(v)}) maps these view-specific features into a single shared representation ziz\_{i}:

| zi\=ϕ​((xi(v))v∈V)∈ℝd,V⊆{E,A,K,D}.z\_{i}=\\phi\\!\\left((x^{(v)}\_{i})\_{v\\in V}\\right)\\in\\mathbb{R}^{d},\\quad V\\subseteq\\{E,A,K,D\\}. | (1) |
| --------------------------------------------------------------------------------------------------------------------------------------------- | --- |

Building on prior multi-view clustering objectives 9577930, we train the model to ensure that representations from heterogeneous views are (i) contradistinctively aligned, (ii) cross-view predictive, and (iii) reconstructible. The overall loss is defined as the weighted sum of these three components, as shown in Equation [2](#S3.E2 "In 3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"):

| ℒ\=ℒcon+λpred​ℒpred+λrec​ℒrec\\mathcal{L}=\\mathcal{L}\_{\\mathrm{con}}+\\lambda\_{\\mathrm{pred}}\\,\\mathcal{L}\_{\\mathrm{pred}}+\\lambda\_{\\mathrm{rec}}\\,\\mathcal{L}\_{\\mathrm{rec}} | (2) |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |

where ℒcon,ℒpred,ℒrec\\mathcal{L}\_{\\mathrm{con}},\\mathcal{L}\_{\\mathrm{pred}},\\mathcal{L}\_{\\mathrm{rec}} are cross-view contrastive loss, dual prediction loss, and within-view reconstruction loss, respectively.

ℒcon\\mathcal{L}\_{\\mathrm{con}}, enforces consistency between embeddings from different views of the same intent unit while separating embeddings from different instances:

| ℒcon\=1\|P​(V)|​∑(p,q)∈P​(V)\[−1N​∑i\=1Nlog⁡exp⁡(⟨zi(p),zi(q)⟩/τ)∑j≠iexp⁡(⟨zi(p),zj(q)⟩/τ)\]\\mathcal{L}\_{\\mathrm{con}}=\\frac{1}{|P(V)|}\\!\\sum\_{(p,q)\\in P(V)}\\Bigg\[-\\frac{1}{N}\\sum\_{i=1}^{N}\\log\\frac{\\exp\\!\\left(\\langle z\_{i}^{(p)},\\,z\_{i}^{(q)}\\rangle/\\tau\\right)}{\\sum\_{j\\neq i}\\exp\\!\\left(\\langle z\_{i}^{(p)},\\,z\_{j}^{(q)}\\rangle/\\tau\\right)}\\Bigg\] | (3) |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |

where, P​(V)P(V) denotes the set of all ordered positive view pairs (p,q)(p,q) within the selected view set VV. The temperature parameter τ\\tau controls the sharpness of the contrastive distribution, whereas NN denotes the number of intent units sampled in a minibatch.

ℒpred\\mathcal{L}\_{\\mathrm{pred}} introduces two projection heads Gp→qG\_{p\\!\\to\\!q} and Gq→pG\_{q\\!\\to\\!p} that learn to predict the embedding of one view from another. Their averaged mapping G\=(Gp→q+Gq→p)/2G=(G\_{p\\!\\to\\!q}+G\_{q\\!\\to\\!p})/2 acts as a symmetric predictor encouraging cross-view consistency—ensuring that one view can reconstruct another within the latent space. The scalar coefficient λpred\\lambda\_{\\mathrm{pred}} balances this term with the others in Equation [2](#S3.E2 "In 3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

| ℒpred\\displaystyle\\mathcal{L}\_{\\mathrm{pred}}                                                                            | \=1\|P​(V)|∑(p,q)∈P​(V)12​N∑i\=1N\[∥Gp→q(zi(p))−zi(q)∥22\\displaystyle=\\frac{1}{|P(V)|}\\!\\sum\_{(p,q)\\in P(V)}\\!\\frac{1}{2N}\\sum\_{i=1}^{N}\\Big\[\\|G\_{p\\!\\to\\!q}(z\_{i}^{(p)})-z\_{i}^{(q)}\\|\_{2}^{2} |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| +∥Gq→p(zi(p))−zi(q)∥22\]\\displaystyle\\hskip 39.83368pt+\\\|G\_{q\\!\\to\\!p}(z\_{i}^{(p)})-z\_{i}^{(q)}\\|\_{2}^{2}\\Big\] | (4)                                                                                                                                                                                                                  |

Finally, ℒrec\\mathcal{L}\_{\\mathrm{rec}} ensures that the shared embedding zi{z\_{i}} retains view-specific semantics by reconstructing each original feature xv(u)x\_{v}^{(u)} through a decoder gv​(⋅)g\_{v}(\\cdot). The weight λrec\\lambda\_{\\mathrm{rec}} determines the relative strength of this reconstruction constraint within the total loss in Equation [2](#S3.E2 "In 3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

| ℒrec\=1\|V|​N​∑v∈V∑i\=1N‖gv​(zi(v))−xi(v)‖22\\mathcal{L}\_{\\mathrm{rec}}=\\frac{1}{|V|\\,N}\\sum\_{v\\in V}\\sum\_{i=1}^{N}\\|g\_{v}(z\_{i}^{(v)})-x\_{i}^{(v)}\\|\_{2}^{2} | (5) |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |

Together, these three objectives jointly align, predict, and reconstruct heterogeneous views, yielding a coherent embedding space where intent-level semantics are preserved. The resulting representation ziz\_{i} compactly captures user intent across multiple modalities. We then organize {ui}\\{u\_{i}\\} hierarchically by ziz\_{i}: first into higher-level intent groups (I​GIG) driven by environment context, and then into subgroups (S​GSG) based on action/keyword and description. These S​GSG representations provide the foundation for extracting recurrent action patterns and constructing abstract skills, as described in Section [3.2](#S3.SS2 "3.2. Skill abstraction based on Intent Subgroups ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"). Details of the encoder are in Appendix [A](#A1 "Appendix A Encoder Details ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

### 3.2\. Skill abstraction based on Intent Subgroups

Given the per-unit embeddings z(u)z^{(u)} from Section [3.1](#S3.SS1 "3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), we organize intents into a two-level index for planning. First, we run HDBSCAN campello2015hierarchical over {z(u)}\\{z^{(u)}\\} to obtain higher-level _intent groups_ (I​GIG) driven primarily by environment/context. Within each I​GIG, a second HDBSCAN partitions units into finer _subgroups_ (S​GSG) using action/keyword and description signals. For every S​GSG, we compute and store its centroid cS​Gc\_{SG} in the same embedding space. At retrieval time, we rank subgroups by the cosine similarity between cS​Gc\_{SG} and a query _intent prototype_. Retrieval index: for each S​GSG we store (i) the centroid cS​Gc\_{SG} (for cosine-based ranking); (ii) top-kk _representative traces_ preselected by proximity to cS​Gc\_{SG} and reranked at query time by similarity to the intent prototype; and (iii) a _support_ count for S​GSG (defined below) used to prefer stable patterns during planning. A detailed ablation on the representation loss and I​G/S​GIG/SG Gating are reported in Appendix [C](#A3 "Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

We then consolidate the low-level action traces inside each S​GSG into a reusable skill. Each intent unit uiu\_{i} in a subgroup is linked to a low-level action sequence: Mi\=(a1,a2,…,am)i.M\_{i}=(a\_{1},a\_{2},\\dots,a\_{m})\_{i}.. To make traces comparable, we map every atomic action ata\_{t} to a pair _\[verb predicate, typed argument fields\]_ by applying an alias map Φ\\Phi that collapses surface variants to a fixed predicate and a fixed set of typed fields. For example, ”focus URL bar” and ”open web site” →\\rightarrowverb=press, arg=address\_bar, verb=text\_input, arg=address\_bar, text:”https://example.com”. Here, a _verb signature_ is the ordered list of canonical predicates in a trace, and an _typed argument field_ is a placeholder (e.g., <url>, <query>, <file\_path>) that will be bound at runtime.

We collect candidates sgskills,k\={Mi∣ui∈S​Gk}\\mathrm{sg}\_{\\mathrm{skills},k}=\\{\\,M\_{i}\\mid u\_{i}\\in SG\_{k}\\,\\} and induce a _skill prototype_ as the medoid under a signature-level dissimilarity d​sigd{\\mathrm{sig}} over verb-predicate sequences. The function dsigd\_{\\mathrm{sig}} is computed on the canonicalized verb-predicate sequences (after applying Φ\\Phi), comparing action patterns at the predicate level while deferring literal-argument handling to the parameterization stage. Let 𝒜\\mathcal{A} denote the verb-predicate alphabet. Thus the subgroup’s _skill prototype_ is defined as:

| 𝒮S​G\=arg⁡mina∈A∗​∑s∈s​gs​k​i​l​l​sdsig​(a,s)\\mathcal{S}\_{SG}=\\arg\\min\_{a\\in A^{\*}}\\;\\sum\_{s\\in{sg}\_{skills}}\\mathrm{d}\_{\\mathrm{sig}}(a,s) | (6) |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |

Next we convert 𝒮S​G\\mathcal{S}\_{SG} into a reusable, _parameterized schema, skill hint_: a verb-predicate sequence together with a typed argument structure. This conversion (i) replaces literal values with typed parameters (the runtime-filled fields), (ii) removes incidental or recovery-specific steps that do not affect goal attainment, and (iii) enforces canonical predicate and field names via Φ\\Phi. We refer to this parameterized schema as a _skill hint_. Both the skill hints {𝒮​S​G}\\{\\mathcal{S}{SG}\\} and the representative traces are stored in plan memory and retrieved at planning time.

If multiple predicate sequences are well supported, we keep several schemas ranked by their _support_, where support counts subgroup members whose similarity to 𝒮S​G\\mathcal{S}\_{SG} exceeds a fixed threshold τ\\tau. _Representative traces_ are the top-kk members minimizing d​sigd{\\mathrm{sig}} to 𝒮​S​G\\mathcal{S}{SG} and serve as concrete exemplars. At planning time, when a retrieved plan is only a partial match, we perform gap filling: we instantiate the selected _skill hint_ 𝒮​S​G\\mathcal{S}{SG} with current-context bindings and insert the resulting steps to complete the missing plan units/steps (Section [4.1](#S4.SS1 "4.1. Planning with Plan Memory and Skill Hints ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")).

## 4\. Intent-aware Planning & Feedback Memory

Building on the intent-level DB introduced in Section [3](#S3 "3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), we now focus on how these abstractions are leveraged during planning and execution. This section details the end-to-end workflow in which the Planner, Plan-Optimizer, and Critic cooperate through plan memory to compose, refine, and verify long-horizon automation. The Planning-Automation part in figure [1](#S1.F1 "Figure 1 ‣ 1. Introduction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") represents the overall automation process after the user request.

### 4.1\. Planning with Plan Memory and Skill Hints

![Refer to caption](2602.17049v2/figures/figure3.png)

Figure 3\. Cache-first planning with plan memory. A query intent is gated by IG and ranked over SG. Case 1 (miss): synthesize a plan from retrieved skill templates. Case 2 (hit): reuse the stored plan. Case 3 (partial): align to the nearest plan and fill gaps with SG-derived skill hints, reducing retries.

This section explains how the Planner agent composes a high-level plan GG for a given command; Figure [3](#S4.F3 "Figure 3 ‣ 4.1. Planning with Plan Memory and Skill Hints ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") summarizes three pathways: cache miss synthesis (Case 1), direct reuse on exact hit (Case 2), and reuse-with-injection on partial hit (Case 3). At a high level, Planner consults I​G/S​GIG/SG centroids in the shared embedding space, plan-memory entries, and M​(u)M(u) sequences; missing spans are completed with normalized SS​GS\_{SG} templates.

When no suitable plan exists in plan memory (Figure [3](#S4.F3 "Figure 3 ‣ 4.1. Planning with Plan Memory and Skill Hints ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), Case 1), the Planner embeds the command into the shared space, gates by the active I​GIG, and ranks candidate S​GSG by centroid similarity. Plan memory stores previously synthesized global plans GG that received _binary_ user approval. Plans not approved are discarded. For each plan-unit slot in the intent prototype, it selects the nearest S​GSG, retrieves the top-2 intent units (uiu\_{i}) from that S​GSG, and uses the GPT-4o model openai2024hello to generate the slot’s steps conditioned on the retrieved MiM\_{i} sequences. A _plan unit_ is a contiguous block of low-level steps in the global plan GG that achieves one subgoal. A _plan-unit slot_ is the placeholder for such a block in the intent prototype that the Planner must populate with executable steps.

Concatenating all slots yields a high-level plan G\={g1,…,gn}G=\\{g\_{1},\\dots,g\_{n}\\}, where each gjg\_{j} expands to a contiguous, execution-ordered list of low-level actions. After the user reviews the generated plan and provides optional feedback, we incorporate the edits and then store GG in plan memory for future reuse. Concretely, GG is materialized as _plan units_—intent-prototype–level chunks of the GG derived from the initial user command:Plan Unit 1: \[step\_1, step\_2, ...\] Plan Unit 2: \[step\_kk, ..., step\_ℓ\\ell\] ...

When a high-similarity plan is found in active I​GIG (Figure [3](#S4.F3 "Figure 3 ‣ 4.1. Planning with Plan Memory and Skill Hints ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), Case 2), the stored GG is retrieved and its slots are bound to the current context; because no gaps remain, the planner skips the synthesis and executes the plan as-is.

When only a partial match is found (Figure [3](#S4.F3 "Figure 3 ‣ 4.1. Planning with Plan Memory and Skill Hints ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), Case 3), the closest stored plan GG is aligned with the intent prototype. Insert missing plan units or steps by injecting the matched subgroup’s SS​GS\_{SG} with current-context bindings (gap filling), after which the finalized GG is executed. This cache-first pipeline reduces re-planning and stabilizes long-horizon execution by combining centroid gating, plan reuse, and hint-based gap filling.

### 4.2\. Optimizing steps by memory & feedback loop

Given a finalized plan GG, execution shifts into a cooperative loop between the Plan-Optimizer and the Critic Agent, utilizing the Plan Memory. The Plan-Optimizer refines each plan unit by referencing similar traces stored in the memory, dynamically adapting its substeps to current screen contexts. The Critic, in turn, monitors the execution and provides immediate feedback signals—success, retryable, or blocked—to correct local deviations or trigger partial replanning when necessary.

For each plan unit p​upu, we compute its representation z(p​u)∈ℝdz^{(pu)}\\in\\mathbb{R}^{d} (Section [3.1](#S3.SS1 "3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) and compare it with subgroup centroids {cS​G}\\{c\_{SG}\\} from plan memory (Section [3.2](#S3.SS2 "3.2. Skill abstraction based on Intent Subgroups ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")). If a subgroup is relevant, its traces are injected as _hints_ into the Plan-Optimizer to guide step execution. After each unit, the Critic evaluates the post-execution state and returns q∈{success,retryable,blocked}q\\in\\{\\textsf{success},\\textsf{retryable},\\textsf{blocked}\\} with an observation oo. If q is retryable, the Plan-Optimizer is re-invoked on the latest state safters^{\\text{after}} with observation observation of the current GUI context (oo) to produce an adjusted subplan gnew′g^{\\prime}\_{\\text{new}}, which updates GG before re-execution.

Algorithm 1  Execution of the Plan utilizing Memory and Feedback Loop

1:Final global plan GG with plan units P​U\={p​u1,…,p​uM}PU=\\{pu\_{1},\\dots,pu\_{M}\\}, where each p​upu is an ordered list of steps; subgroup collection S​GSG with centroids cS​G∈ℝdc\_{SG}\\in\\mathbb{R}^{d} (representation space from Section [3.1](#S3.SS1 "3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")); for every p​u∈P​Upu\\in PU, its representation z(p​u)∈ℝdz^{(pu)}\\in\\mathbb{R}^{d} (precomputed via the encoder in Section [3.1](#S3.SS1 "3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")); action space AA.

2:Execution outcome

3:for each plan unit p​upu in P​UPU do

4: hint ←\\leftarrow InjectHint(pu, S​GSG, z(p​u)z^{(pu)})

5: for each step gg in p​upu do

6: s←s\\leftarrow GUI Grounding of the current screen

7: (a,g′,o)←(a,g^{\\prime},o)\\leftarrow Plan-Optimizer(s,g,G,p​u,o,hints,g,G,pu,o,\\textit{hint})

8: Execute action aa in the current GUI context

9: safter←s^{\\text{after}}\\leftarrow GUI Grounding of the screen after finishing p​upu

10: (q,o)←(q,o)\\leftarrow Critic(p​u,G,safterpu,G,s^{\\text{after}})

11: if q\=\=successq==\\textsf{success} then

12: continue to next p​upu

13: else if q\=\=retryableq==\\textsf{retryable} then

14: (a,gnew′,o)←(a,g^{\\prime}\_{\\text{new}},o)\\leftarrow Plan-Optimizer(safter,g,G,p​u,o,hints^{\\text{after}},g,G,pu,o,\\textit{hint})

15: Apply gnew′g^{\\prime}\_{\\text{new}} to adjust the prior g′g^{\\prime}

16: else

17: return (G,BLOCKED)(G,\\textsf{BLOCKED})

18:return (G,SUCCESS)(G,\\textsf{SUCCESS})

As shown in Algorithm [1](#alg1 "Algorithm 1 ‣ 4.2. Optimizing steps by memory & feedback loop ‣ 4. Intent-aware Planning & Feedback Memory ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), the Planner hands over the plan units to the Plan-Optimizer, which integrates hints from prior traces to refine step execution. The Critic then decides whether to proceed, request an adjustment, or terminate. Through this memory-guided collaboration, specialized agents coordinate to minimize redundant re-planning and improve robustness by reusing traces that previously led to success.

GUI Grounding refers to the process of enumerating all actionable GUI components on the current screen, similar to the screen parsing method used in UFO zhang2024ufo. The resulting state ss includes such component data together with summary metadata, composed of window title, panel names and component counts captured from the environment. Each step gg denotes an individual operation in the global plan GG, composed of an action aa (e.g., click, text input, open) and its corresponding object targets; thus aa specifies the interaction primitive, whereas gg represents the full executable tuple (a,object)(a,\\text{object}).

The InjectHint function searches the plan memory for previous plan units whose representations z(p​u)z^{(pu)} are most similar to the current one, and uses their traces as contextual hints guiding the next execution steps. Example of Planner-Plan-Optimizer-Critic interactions is in Appendix [B](#A2 "Appendix B Framework Details (Planner-Plan-Optimizer-Critic) ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

## 5\. Ablation & Case Studies

### 5.1\. Evaluation Setup

We evaluate our design on 286 real-world GUI tasks: 100 in-house, 116 from WebVoyager he2024webvoyager (643 total), and 70 from ScreenAgent niu2024screenagent (70 sessions). Tasks span local applications, web platforms, productivity tools, and cross-application workflows.

For task mining, we collect 30 active hours of interaction traces across 18 sessions, yielding 113 trace files. The mined corpus is intentionally distribution-shifted from the test suite: traces skew toward Local/App, while the evaluation set contains more Web/Crossover tasks. The traces cover 36 domains, whereas the 286-task suite spans 63 domains; only 22 overlap (34.92%), leaving 41 unseen test domains (65.07%). This setup stresses generalization of mining and retrieval rather than memorization. Domain distributions are detailed in Appendix [D](#A4 "Appendix D Domain level distributions of dataset/testcases ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

All agents use the same atomic GUI action interface and identical timeout policies. We report task success (74.83%), average completion ratio (91.14%), Step Efficiency Ratio(successful steps / actual execution steps; higher is better). Differences are reported in percentage points (pp).

### 5.2\. End-to-End Execution of Ablated Models

We ablate each component to analyze its impact on long-horizon planning stability and execution depth.

Table 1\. Component-wise ablation on planning. We report task success (%) and averaged plan completion (%).

| Method                                  | Success (%) ↑\\uparrow | Completion (%) ↑\\uparrow |
| --------------------------------------- | ---------------------- | ------------------------- |
| BB                                      | 22.73                  | 33.78                     |
| B+TgB+T\_{g}                            | 46.43                  | 57.41                     |
| B+TS​G+ZB+T\_{SG}+Z                     | 54.64                  | 77.56                     |
| B+TS​G+SS​G+P​MB+T\_{SG}+S\_{SG}+PM     | 53.85                  | 81.23                     |
| B+TS​G+Z+P​MB+T\_{SG}+Z+PM              | 62.51                  | 85.00                     |
| B+TS​G+Z+SS​G+P​MB+T\_{SG}+Z+S\_{SG}+PM | 74.83                  | 91.14                     |

For Table [1](#S5.T1 "Table 1 ‣ 5.2. End-to-End Execution of Ablated Models ‣ 5. Ablation & Case Studies ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), Completion denotes averaged plan completion (executed steps / synthesized plan steps), measuring execution progress beyond binary success.

We denote components as:BB (baseline planner–executor),TgT\_{g}, TS​GT\_{SG} (greedy vs. I​G/S​GIG/SG\-gated trace retrieval),ZZ (intent-level representation),SS​GS\_{SG} (subgroup skill hints),P​MPM (plan memory reuse)

Starting from BB (22.73% success), adding greedy trace retrieval (BB+TgT\_{g}) improves success by +23.7, pp showing that user traces substantially reduce cold-start errors but still induce drift in long horizons. Replacing greedy retrieval with I​G/S​GIG/SG gating + ZZ brings a further +8.21, pp success gain and +20.15, pp completion gain, showing that organizing traces into representation-learned intent subgroups significantly stabilizes long-horizon execution. Even without ZZ, combining SS​GS\_{SG} \+ P​MPM achieves a high task completion rate (81.23%), indicating that skill hints and plan memory alone substantially improve execution depth.

The full system (BB+TS​GT\_{SG}+ZZ+SS​GS\_{SG}+P​MPM) achieves the best success and completion overall, demonstrating that representation learning, intent-level gating, skill abstraction, and plan reuse act complementarily. Evaluation on step-wise planning consistency of the full system is in Appendix [E](#A5 "Appendix E Planning Consistency ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

### 5.3\. Case Study

To illustrate the framework, we consider a task where the user asks the system to summarize a previously viewed lightweight-ML video and record the result in a personal workspace. This requires retrieval, reasoning, and coordination across multiple applications.

![Refer to caption](2602.17049v2/figures/example.png)

Figure 4\. IntentCUA in action: the system recalls intent units from memory and decomposes a multi-application command into intent-level plan units, each executed through learned skills and recomposed into an end-to-end automation plan.

Figure [4](#S5.F4 "Figure 4 ‣ 5.3. Case Study ‣ 5. Ablation & Case Studies ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") shows the execution process. The Planner retrieves relevant traces from plan memory, including prior interactions with the video platform, AI chatbot, and workspace application, and reconstructs the video source from the user’s history. It decomposes the request into structured intent-level plan units, each grounded into executable GUI actions by the Plan-Optimizer, while the Critic monitors progress and handles local inconsistencies. Through hierarchical reasoning and memory-guided skill retrieval, the system completes the multi-application task while maintaining intent coherence.

A failure case occurs when an unexpected pop-up appears during execution. Because underlying components become occluded, the grounding module fails to detect them, leading to incorrect retries. This highlights a limitation of script-based GUI grounding under transient interface changes.

## 6\. Experiments

We compare IntentCUA against two representative desktop GUI agents chosen for methodological diversity: UI-TARS-1.5 ui-tars-15-seed, an RL-based visual planner–executor with self-evolving policies and screen grounding, and UFO2 zhang2025ufo2, a trajectory-centric Windows automation agent that organizes demonstrations as executable sequences. Together these baselines span reinforcement learning–driven automation versus demonstration-driven planning, and both operate at the level of atomic GUI actions, ensuring comparability with our interface. We evaluate 286 tasks (the same evaluation suite described in Section [5.1](#S5.SS1 "5.1. Evaluation Setup ‣ 5. Ablation & Case Studies ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) and report task success rate, Step Efficiency Ratio(SER), and Latency, further analyzing robustness by step-length bins, each step defined as a atomic action performed by the agent. SER is defined as the ratio of successful steps to total steps, ranging from 0 to 1\. Latency is measured as the execution time per task, reflecting not only the number of steps but also the overhead of perception and planning.

### 6.1\. Robust Long-Horizon Planning Efficiency

Table 2\. End-to-end success rate comparison across datasets (%). Columns show WebVoyager, ScreenAgent, our in-house suite, and overall average.

| Method                      | WebVoyager | ScreenAgent | Ours | Total(%) |
| --------------------------- | ---------- | ----------- | ---- | -------- |
| UI-TARS-1.5 ui-tars-15-seed | 35.9       | 42.9        | 46.0 | 38.8     |
| UFO2 zhang2025ufo2          | 69.0       | 41.4        | 38.0 | 51.2     |
| IntentCUA (ours)            | 71.6       | 77.1        | 78.0 | 74.8     |

![Refer to caption](2602.17049v2/figures/figure4.png)

Figure 5\. Success rate by step length (bin size = 5 steps). The x-axis shows step-length bins and the y-axis shows task success rate (%).

We evaluate how each agent sustains task completion as sequence length increases, focusing on the robustness of long-horizon planning. Table [2](#S6.T2 "Table 2 ‣ 6.1. Robust Long-Horizon Planning Efficiency ‣ 6. Experiments ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") and Figure [5](#S6.F5 "Figure 5 ‣ 6.1. Robust Long-Horizon Planning Efficiency ‣ 6. Experiments ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") summarize overall and step-wise success trends across 286 evaluation tasks. IntentCUA achieves the highest overall success rate of 74.8%, compared to 51.2% for UFO2 and 38.8% for UI-TARS-1.5, yielding relative improvements of about +23.6 and +36 percentage points, respectively.

Notably, IntentCUA performs consistently well across all datasets, achieving 71.6% on the web-based WebVoyager, 77.1% on the cross-application ScreenAgent, and 78.0% on our in-house local suite, demonstrating that its advantage is not confined to a specific benchmark. While agents like UFO2 specialize in narrow domains such as web navigation, IntentCUA generalizes effectively to heterogeneous desktop environments that include both online and offline contexts, confirming its versatility and domain robustness.

As shown in Figure [5](#S6.F5 "Figure 5 ‣ 6.1. Robust Long-Horizon Planning Efficiency ‣ 6. Experiments ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"), IntentCUA maintains stable performance even as task length grows: 85.9% at 10–15 steps, 72.5% at 15–20, and 65.0% at 20–25, while still retaining 42.9% beyond 30 steps. Both baselines, in contrast, decline sharply after 20 steps, dropping below 20%. This gradual degradation indicates that IntentCUA’s planning remains consistent and resistant to drift even in extended workflows spanning multiple windows and applications.

The stability across longer horizons can be attributed to its _intent-aware retrieval_ and _plan memory reuse_, which enable the planner to recall previously successful subplans aligned with the current intent embedding rather than regenerating them from scratch. Together, these results confirm that IntentCUA achieves robust and generalizable long-horizon planning efficiency, effectively preserving goal coherence and minimizing redundant re-planning under complex, real-world desktop environments.

![Refer to caption](2602.17049v2/figures/figure5.png)

Figure 6\. Performance by task length (bin size = 5 steps). Left: Step Efficiency Ratio (SER). Right: Average latency per task (minutes)

### 6.2\. Stable & Scalable Planning Efficiency and Latency

We examine efficiency using two complementary metrics: the Step Efficiency Ratio (SER; Left) and the average latency per task (Right), as shown in Figure [6](#S6.F6 "Figure 6 ‣ 6.1. Robust Long-Horizon Planning Efficiency ‣ 6. Experiments ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents"). IntentCUA achieves the highest SER of 0.91, exceeding UI-TARS (0.85) and UFO2 (0.82). While SER in IntentCUA decreases moderately from 0.93 at 10–15 steps to 0.88 at 20–25, it remains consistently above 0.85 even for the longest tasks, indicating that most actions continue to contribute effectively to progress. In contrast, both baselines show sharper declines across similar ranges, suggesting increased redundancy or re-planning.

Latency patterns further highlight scalability. IntentCUA’s average execution time is 1.46 minutes, approximately 4.5× lower than the baselines (UFO2: 6.63 min, UI-TARS: 9.82 min). Its latency increases smoothly with task length—for instance, from 0.95 min at 10–15 steps to 2.01 min at 20–25—showing near-linear growth. By comparison, UI-TARS exhibits irregular delays that expand sharply with step count, and UFO2 shows unstable spikes on shorter tasks due to looped retries.

These results demonstrate that IntentCUA sustains high planning efficiency and low, predictable latency as task complexity increases. Its memory-guided retrieval and feedback design minimize redundant computation, yielding a scalable and robust planning policy suitable for real desktop automation.

## 7\. Conclusion

We presented IntentCUA, a framework that transforms raw interaction traces into multi-view intent representations, abstracts them into reusable skills, and integrates these with plan memory to support stable long-horizon desktop automation. The system combines representation learning, hierarchical skill induction, and memory-guided planning to reduce re-planning and improve stability across complex workflows.

In experiments, IntentCUA achieved a 74.8% task success rate with a step efficiency ratio of 0.91, outperforming both UI-TARS-1.5 (RL-based) and UFO2 (trajectory-centric) by 4.5×\\times times reduced latency. It also maintained over 40% success on long-horizon tasks exceeding 30 steps. Ablation studies show that each component contributes to robustness and efficiency, with the full design providing the greatest improvements on longer tasks. While IntentCUA shows consistent reasoning and cross-application generalization, several aspects remain open for refinement. Retrieval efficiency may fluctuate as the plan memory grows, though this mainly affects latency rather than accuracy. Graph-based retrieval and lightweight vision cues could further enhance robustness, allowing the system to adapt more smoothly to dynamic and visually changing interfaces.

## Acknowledgments

This work was supported by the National Research Foundation of Korea(NRF) grant (No. RS-2022-NR066631, No. RS-2025-02216282) and Institute of Information & communications Technology Planning & Evaluation (IITP) grant (No.RS-2022-II220025) funded by the Korea government(MSIT) and Ministry of Trade, Industry and Energy of Korea (MOTIE RS 2023 00258591).

## References

## Appendix A Encoder Details

This appendix summarizes the implementation details of the multi-view encoder described in Section [3.1](#S3.SS1 "3.1. Intent-level Representation Learning ‣ 3. Intent-level Representation Learning & Skill Abstraction ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

#### Encoder Architecture.

Each view (ENV, ACT/KEY, DES) is embedded using OpenAI text-embedding-3-large, producing a 3072-dimensional vector. Each embedding is mapped to a shared latent space via a view-specific 2-layer MLP projection head:

| 3072→256→256,3072\\rightarrow 256\\rightarrow 256, |
| -------------------------------------------------- |

with GeLU activation, dropout (p\=0.05p=0.05), and LayerNorm, yielding

| zi(v)∈ℝ256.z\_{i}^{(v)}\\in\\mathbb{R}^{256}. |
| --------------------------------------------- |

Cross-view consistency is enforced using six symmetric dual predictors, one for each ordered view pair. Each predictor is a lightweight MLP (256→128→256256\\rightarrow 128\\rightarrow 256) used only during training. Additionally, a linear decoder (256→3072256\\rightarrow 3072) is applied per view to reconstruct the original embedding for reconstruction regularization.

#### Shared Representation and Fusion Weights.

The final shared intent representation is computed as a weighted fusion:

| zi\=0.4​zi(E)+0.3​zi(A)+0.3​zi(D).z\_{i}=0.4\\,z\_{i}^{(E)}+0.3\\,z\_{i}^{(A)}+0.3\\,z\_{i}^{(D)}. |
| -------------------------------------------------------------------------------------------------- |

The environment view is assigned the largest weight because execution environment provides the most stable contextual signal in desktop automation and serves as the primary driver for upper-level intent group (IG) formation. This environment-centric fusion improves the stability of hierarchical clustering while still preserving action- and description-level variability for finer subgroups (SG).

For model training, we used a learning rate of 1×10−31\\times 10^{-3}, with λpred\=0.1\\lambda\_{\\mathrm{pred}}=0.1, λrec\=0.05\\lambda\_{\\mathrm{rec}}=0.05, and a contrastive temperature τ\=0.1\\tau=0.1.

#### Tensor Shapes.

For a minibatch of size NN, the encoder operates on:

| x(v)∈ℝN×3072,z(v)∈ℝN×256,z∈ℝN×256.x^{(v)}\\in\\mathbb{R}^{N\\times 3072},\\quad z^{(v)}\\in\\mathbb{R}^{N\\times 256},\\quad z\\in\\mathbb{R}^{N\\times 256}. |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- |

## Appendix B Framework Details (Planner-Plan-Optimizer-Critic)

![Refer to caption](2602.17049v2/figures/interaction.png)

Figure 7\. Planner–Plan-Optimizer–Critic interaction. The Planner decomposes a command into structured Plan Units and retrieves or synthesizes a global plan. The Plan-Optimizer grounds each unit into executable GUI actions conditioned on the current state, while the Critic validates the post-state SafterS^{\\text{after}} and triggers local re-optimization if needed.

#### Planner

At inference time, the Planner maps a natural-language command cc into the same structured format used for log labeling by prompting the LLM to produce task units of the form Task Unit: ENV\[…\] ACT\[…\], Task k: ENV\[…\] ACT\[…\] with short descriptions (e.g., “search dog at a browser” → ENV\[local/Windows, web/searching browser\], ACT\[open browser, search\]).

From these views, it builds an intent prototype and retrieves candidate plans from memory. A cached plan is reused only if its action coverage with respect to the current breakdown is high: in practice, we require that the plan already contains most of the required ACTs (allowing at most 2 missing ACTs per command). For each such missing ACT, we retrieve the corresponding intent subgroup, select the skill template most frequently observed in the logs, instantiate its placeholders from cc (e.g., query = ”dog”), and splice the resulting steps into the cached plan. If no cached plan satisfies this condition, the Planner falls back to RAG using representative logs as examples. The final output is a global plan G = gi{g\_{i}}, where each step gig\_{i} \= (action, object) uses one of a fixed set of 17 low-level GUI actions (e.g., text input, click, doubleclick, press, switch focus, save, copy…).

#### Execution(Plan-Optimizer → Critic interaction)

Execution consists of a Plan-Optimizer that grounds each gg into concrete GUI actions, and a Critic that validates the post-state and triggers local recovery. Each step gg from the global plan is expanded into an actionable sequence g′g^{\\prime} using a fixed library of default action templates (e.g., open : doubleclick icon or click taskbar → type target →press enter), ensuring grounding into atomic GUI actions.

The Plan-Optimizer conditions on (1) task-unit context, (2) the parsed screen state ss, and (3) a retrieved plan hint by matching z(p​u)z^{(pu)} to the nearest subgroup centroid. Hints contain historical ENV/ACT/DES tuples and action-object traces, biasing execution toward stable patterns rather than free-form generation.

After each plan unit, the Critic inspects the post-state safters^{\\text{after}} via a structured prompt that checks window focus, component availability, and compatibility with the next expected step and returns retryable=success, retryable, blocked which triggers a localized re-optimization from safters^{\\text{after}}, avoiding global re-planning, while ‘blocked’ indicates that neither template-based execution nor exemplar-guided adjustment provides a safe continuation. A step-by-step example of this interaction is illustrated in Figure [7](#A2.F7 "Figure 7 ‣ Appendix B Framework Details (Planner-Plan-Optimizer-Critic) ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

## Appendix C Ablation on the Representation Loss

Table 3\. Representation loss ablation on intent embedding quality. We report size-weighted density separation (inter/intra) over all HDBSCAN subgroups.

| Loss Variant             | Separation ↑\\uparrow |
| ------------------------ | --------------------- |
| Baseline Embedding       | 5.60                  |
| InfoNCE only             | 5.64                  |
| InfoNCE + Prediction     | 6.92                  |
| InfoNCE + Reconstruction | 23.17                 |
| Full (Con + Pred + Rec)  | 7.74                  |

Table 4\. ENV/ACT purity under different representation loss variants. We report mean purity with standard deviation in parentheses.

| Loss Variant             | ENV purity  | ACT purity  |
| ------------------------ | ----------- | ----------- |
| Baseline Embedding       | 0.83(0.19)  | 0.48(0.25)  |
| InfoNCE only             | 0.82 (0.22) | 0.37 (0.22) |
| InfoNCE + Prediction     | 0.83 (0.21) | 0.42 (0.26) |
| InfoNCE + Reconstruction | 0.86 (0.19) | 0.42 (0.26) |
| Full (Con + Pred + Rec)  | 0.84 (0.20) | 0.42 (0.23) |

We analyze density separation and cluster purity with respect to ENV and ACT tags for further ablation.

To address concerns about the representation objective, we compare four variants: InfoNCE-only, InfoNCE + cross-view prediction, InfoNCE + reconstruction, and the full loss.

| Sepw\=∑I​G∑S​G∈I​G\|S​G|​Inter​(S​G)Intra​(S​G)∑I​G∑S​G∈I​G|S​G|\\mathrm{Sep}\_{\\mathrm{w}}=\\frac{\\sum\\limits\_{IG}\\sum\\limits\_{SG\\in IG}|SG|\\;\\frac{\\mathrm{Inter}(SG)}{\\mathrm{Intra}(SG)}}{\\sum\\limits\_{IG}\\sum\\limits\_{SG\\in IG}|SG|} | (7) |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |

| Intra​(S​G)\\displaystyle\\mathrm{Intra}(SG) | \=1\|S​G|​∑x∈S​Gd​(x,𝐜S​G)\\displaystyle=\\frac{1}{|SG|}\\sum\_{x\\in SG}d(x,\\mathbf{c}\_{SG})                           | (8) |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --- |
| Inter​(S​G)\\displaystyle\\mathrm{Inter}(SG) | \=minS​G′≠S​G⁡d​(𝐜S​G,𝐜S​G′)\\displaystyle=\\min\_{SG^{\\prime}\\neq SG}d(\\mathbf{c}\_{SG},\\mathbf{c}\_{SG^{\\prime}}) |     |

| μX\\displaystyle\\mu^{X}    | \=1\|𝒮​𝒢|​∑I​G∑S​G∈I​GPurityX​(S​G)\\displaystyle=\\frac{1}{|\\mathcal{SG}|}\\sum\_{IG}\\sum\_{SG\\in IG}\\mathrm{Purity}^{X}(SG)                                           | (9) |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| σX\\displaystyle\\sigma^{X} | \=1\|𝒮​𝒢|​∑I​G∑S​G∈I​G(PurityX​(S​G)−μX)2\\displaystyle=\\sqrt{\\frac{1}{|\\mathcal{SG}|}\\sum\_{IG}\\sum\_{SG\\in IG}\\left(\\mathrm{Purity}^{X}(SG)-\\mu^{X}\\right)^{2}} |     |

| PurityX​(S​G)\=maxc⁡\|{t∈S​G:tagX​(t)\=c}||S​G|\\mathrm{Purity}^{X}(SG)=\\frac{\\max\_{c}\\left|\\{\\,t\\in SG:\\mathrm{tag}^{X}(t)=c\\}\\right|}{|SG|} | (10) |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- |

We report (1) size-weighted density separation (inter/intra: Eq [8](#A3.E8 "In Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) in Eq [7](#A3.E7 "In Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") over all HDBSCAN subgroups in Table [3](#A3.T3 "Table 3 ‣ Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") and (2) semantic purity(Eq [9](#A3.E9 "In Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) measured as majority ENV/ACT ratios(Eq [10](#A3.E10 "In Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) within each subgroup in Table [4](#A3.T4 "Table 4 ‣ Appendix C Ablation on the Representation Loss ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents").

The full loss improves the separation ratio from 5.64 (InfoNCE-only) to 7.74, while InfoNCE + reconstruction produces an inflated separation score of 23.17 due to extreme micro-clusters (size=2), indicating over-fragmentation rather than robust intent abstraction. In terms of semantic consistency, ENV purity increases from 0.82 (InfoNCE-only) to 0.84 (Full), and ACT purity improves from 0.37 to 0.42\. Reconstruction yields the highest ENV purity (0.86) but with higher fragmentation, while Prediction consistently improves ACT purity (0.42 vs. 0.37 in InfoNCE-only). The full objective maintains balanced ENV/ACT purity (0.84 / 0.42) with reduced variance (ENV std 0.20, ACT std 0.23), suggesting more stable and semantically coherent intent embeddings.

## Appendix D Domain level distributions of dataset/testcases

![Refer to caption](2602.17049v2/figures/data_dist.png)

Figure 8\. Domain distribution of collected trace data. Each slice indicates a domain category and its proportion within the trace corpus (%).

![Refer to caption](2602.17049v2/figures/testcase_dist.png)

Figure 9\. Domain distribution of the 286 evaluation testcases. Each slice shows a domain category and the success rate achieved within that domain (%).

Figure [8](#A4.F8 "Figure 8 ‣ Appendix D Domain level distributions of dataset/testcases ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") shows the domain distribution of the collected trace corpus. The trace data are skewed toward Local/App environments, with several long-tail domains having only a few interaction sessions. In contrast, the evaluation suite (Figure [9](#A4.F9 "Figure 9 ‣ Appendix D Domain level distributions of dataset/testcases ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents")) contains a broader Web/Crossover share and substantially more domains overall. This asymmetry reflects the intentional distribution shift described in the main text.

Importantly, domain-level success rates in Figure [9](#A4.F9 "Figure 9 ‣ Appendix D Domain level distributions of dataset/testcases ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") indicate that performance does not strictly correlate with trace frequency. Several domains with very limited or no traces still achieve non-trivial success rates, suggesting that the planner generalizes beyond memorized trajectories. While trace sparsity and bias remain limitations, these statistics provide additional transparency regarding domain coverage and generalization behavior.

## Appendix E Planning Consistency

To further assess stability under system complexity, we introduce step consistency as a quantitative measure of plan repeatability. For each of the 286 testcases, we execute planning five times and compare the resulting plans. For each plan unit p​upu, we examine whether the generated step sequence is consistently reproduced across all five runs. A p​upu is counted as consistent if the pairwise cosine similarity between corresponding step embeddings exceeds a threshold of 0.93 in all comparisons. Step consistency is defined as the proportion of such consistent p​upu instances within each benchmark split.

Table [5](#A5.T5 "Table 5 ‣ Appendix E Planning Consistency ‣ IntentCUA: Learning Intent-level Representations for Skill Abstraction and Multi-Agent Planning in Computer-Use Agents") reports the mean and standard deviation across domains. The results indicate stable planning behavior across datasets, including unseen domains. Despite distribution shift and sparse traces, the Planner–Plan-Optimizer loop maintains high repeatability, suggesting that structural constraints (e.g., ENV derived from window structure and ACT from UI semantics) effectively reduce LLM drift and labeling variance.

Table 5\. Step consistency (%) across five repeated planning runs per testcase (cosine threshold = 0.93).

| WebVoyager | ScreenAgent | Ours | Total |      |
| ---------- | ----------- | ---- | ----- | ---- |
| Mean (%)   | 70.3        | 81.1 | 86.2  | 78.5 |
| STD (%)    | 8.2         | 5.3  | 7.9   | 7.8  |
