# Chapter 4: Problem Statement and Objectives

**Project Title:** An Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Author:** Saksham Bhosale  
**Repository:** `D:\Projects\agentic-code-reviewer`  
**Execution Branch:** `feat/phase-7-evaluation`  

---

## 4.1 Problem Formulation

In a modern Git-based software development lifecycle, a code review task is initiated when a developer submits a pull request proposing modifications from a base commit $C_{\text{base}}$ to a head commit $C_{\text{head}}$.

Formally, the review input is defined as a tuple:
$$\mathcal{I} = \langle R, C_{\text{base}}, C_{\text{head}}, \Delta, \mathcal{M} \rangle$$
Where:
* $R$ denotes the repository context (source files, dependency manifests, configuration files).
* $C_{\text{base}}$ and $C_{\text{head}}$ represent the Git commit SHAs defining the change boundary.
* $\Delta = \{\delta_1, \delta_2, \dots, \delta_n\}$ represents the unified diff, where each file diff $\delta_i$ consists of added, deleted, and modified hunks with explicit source line numbers:
  $$\delta_i = \langle \text{path}_i, \text{hunks}_i \rangle$$
* $\mathcal{M}$ represents metadata associated with the pull request (title, description, author, branch target).

Let $\mathcal{D}^* = \{d_1^*, d_2^*, \dots, d_m^*\}$ represent the unknown set of ground truth software defects introduced or exposed by the diff $\Delta$. Each defect $d^* \in \mathcal{D}^*$ is characterized by an affected file path, target line interval $[L_{\text{start}}, L_{\text{end}}]$, defect category (e.g., Security, Bug Logic, Error Handling, Test Adequacy), severity level, and technical explanation.

An automated code review system $\Phi$ maps the review input $\mathcal{I}$ to a set of predicted candidate review findings $\mathcal{F}$:
$$\Phi(\mathcal{I}) \to \mathcal{F} = \{f_1, f_2, \dots, f_k\}$$
Where each candidate finding $f_j \in \mathcal{F}$ contains:
$$f_j = \langle \text{file}_j, \text{line}_j, \text{category}_j, \text{severity}_j, \text{title}_j, \text{explanation}_j, \text{suggestion}_j \rangle$$

### 4.1.1 The Core Research Dilemma
The fundamental challenge of automated code review is that the review space is open-ended and asymmetric:
1. **The High Cost of False Positives:** Software developers have a low tolerance for automated alerts that do not represent genuine defects. A comment that asserts a false security flaw, suggests an invalid syntax change, or flags a benign idiom demands cognitive effort from the author to investigate and rebut, creating frustration and eroding confidence in CI/CD automation [9, 10].
2. **The High Cost of False Negatives:** Merging critical logic errors, unhandled exceptions, or security vulnerabilities into production branches incurs severe remediation costs, service disruptions, or data breaches [1, 3].
3. **The Unanchored Comment Problem:** Monolithic generative models frequently generate advice that cannot be anchored to an exact modified line in the pull request diff, rendering the critique un-actionable in code review interfaces like GitHub or GitLab.

---

## 4.2 The Alert Fatigue Dilemma

In human-computer interaction (HCI) and software engineering, **Alert Fatigue** describes the cognitive desensitization that occurs when an engineer is subjected to a high volume of frequent, low-confidence, or false automated alerts [9, 10]. 

When developers experience alert fatigue:
* They begin dismissing automated review comments without reading them.
* Automated review bots are perceived as "noise generators" rather than intelligent assistants.
* Teams routinely disable automated CI bots or configure repository rules to ignore automated review findings.

Empirical studies indicate that if an automated tool's False Discovery Rate exceeds $20\%$ to $30\%$ ($\text{FDR} > 0.30$), developers rapidly abandon the tool [9]. A monolithic LLM reviewer exhibiting an $\text{FDR}$ of $80.0\%$ (as measured in Chapter 7) is practically unusable in industrial settings, regardless of how fluently its comments are phrased. Therefore, **minimizing the False Discovery Rate to near-zero while maximizing True Positive recall is the primary engineering requirement for viable automated peer review**.

---

## 4.3 Mathematical Formulation of Evaluation Metrics

To rigorously assess code review quality, we establish formal definitions of evaluation metrics at the **finding level**.

### 4.3.1 Matching Criteria
A predicted finding $f \in \mathcal{F}$ is matched against a ground truth defect $d^* \in \mathcal{D}^*$ using a deterministic matching function $\mu(f, d^*) \in \{0, 1\}$:
$$\mu(f, d^*) = 1 \iff \begin{cases}
f.\text{file} = d^*.\text{file} \\
[f.\text{line}_{\text{start}}, f.\text{line}_{\text{end}}] \cap [d^*.\text{line}_{\text{start}} - \tau, d^*.\text{line}_{\text{end}} + \tau] \neq \emptyset \\
f.\text{category} = d^*.\text{category}
\end{cases}$$
Where $\tau$ represents an allowable line-tolerance window ($\tau = 3$ lines) to accommodate slight differences in reviewer line-anchoring across multi-line statements.

Based on matching, predictions and ground truth defects are classified into:
* **True Positives (TP):** Genuine ground truth defects successfully matched by at least one predicted finding:
  $$\text{TP} = |\{d^* \in \mathcal{D}^* \mid \exists f \in \mathcal{F} \text{ such that } \mu(f, d^*) = 1\}|$$
* **False Positives (FP):** Predicted findings that do not correspond to any ground truth defect, including spurious warnings, hallucinations, and duplicate alerts on the same coordinate:
  $$\text{FP} = |\{f \in \mathcal{F} \mid \forall d^* \in \mathcal{D}^*, \mu(f, d^*) = 0\}| + \text{Duplicates}$$
* **False Negatives (FN):** Ground truth defects that the review system failed to identify:
  $$\text{FN} = |\{d^* \in \mathcal{D}^* \mid \forall f \in \mathcal{F}, \mu(f, d^*) = 0\}|$$

### 4.3.2 Quantitative Metric Definitions

1. **Precision:** The proportion of predicted findings that represent genuine defects:
   $$\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}$$
2. **Recall (True Positive Rate):** The proportion of ground truth defects successfully detected:
   $$\text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}$$
3. **F1-Score:** The harmonic mean of precision and recall:
   $$\text{F1} = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}} = \frac{2 \cdot \text{TP}}{2 \cdot \text{TP} + \text{FP} + \text{FN}}$$
4. **Finding-Level False Discovery Rate (FDR):**
   The proportion of reported findings that are false alerts:
   $$\text{FDR} = \frac{\text{FP}}{\text{TP} + \text{FP}} = 1 - \text{Precision}$$

> **Critical Distinction: FDR vs. FPR**  
> In literature on medical diagnostics or binary classification, False Positive Rate is defined as $\text{FPR} = \frac{\text{FP}}{\text{FP} + \text{TN}}$. In automated code review, however, the concept of **True Negatives (TN)** is ill-defined: an unconstrained reviewer examines lines that do *not* contain bugs, but counting every non-buggy line or token as a "True Negative" inflates the denominator by thousands, rendering standard $\text{FPR}$ meaningless and misleadingly close to zero. Consequently, this dissertation strictly uses the **finding-level False Discovery Rate ($\text{FDR}$)**, which measures the probability that a comment posted by the bot on a pull request is a false alarm.

5. **Relative FDR Reduction:** The percentage reduction in False Discovery Rate achieved by the proposed system compared to the monolithic single-LLM baseline:
   $$\Delta_{\text{FDR}} = \frac{\text{FDR}_{\text{single\_llm}} - \text{FDR}_{\text{agentic}}}{\text{FDR}_{\text{single\_llm}}} \times 100\%$$

6. **Confidence Intervals (Wilson Score Interval):**
   For empirical proportions $p \in \{\text{Precision}, \text{Recall}, \text{FDR}\}$ over $n$ total trials, confidence intervals are computed using the Wilson score interval:
   $$w = \frac{p + \frac{z^2}{2n} \pm z \sqrt{\frac{p(1-p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$
   Where $z = 1.96$ corresponds to a $95\%$ confidence level.

---

## 4.4 Project Goals and Measurable Objectives

To provide a clear, empirical standard for project success, this dissertation establishes five primary objectives:

| Objective ID | Dimension | Target Metric / Goal | Realized Achievement | Status |
| :---: | :--- | :--- | :--- | :---: |
| **OBJ-1** | **FDR Reduction** | Achieve $\ge 40\%$ relative reduction in False Discovery Rate compared to Single-LLM | **$100.0\%$ Relative FDR Reduction** ($80.0\% \to 0.0\%$) | **MET & SURPASSED** |
| **OBJ-2** | **High Defect Recall** | Maintain defect detection Recall $\ge 80\%$ across the benchmark corpus | **$95.65\%$ Recall** (22/23 defects detected) | **MET & SURPASSED** |
| **OBJ-3** | **Zero External Cost** | Complete review inference using local open-weights LLMs without external API costs | **$0.00 Total Cost** via local Ollama `qwen3:4b-instruct` | **MET & VERIFIED** |
| **OBJ-4** | **Adversarial Verification** | Eliminate hallucinated findings via an independent adversarial critic | **57 False Positives Eliminated** ($57 \to 0$ FP) | **MET & VERIFIED** |
| **OBJ-5** | **Publication Safety** | Enforce multi-tiered publication gates preventing unverified comments | **100% Gated** (Zero comments posted when unconfigured) | **MET & VERIFIED** |

*Table 4.1: Measurable project objectives, target criteria, and verified results.*

By fulfilling each of these objectives, the framework proves that generative AI can be transformed into a reliable, enterprise-grade software engineering tool when bound by deterministic evidence and adversarial verification.
