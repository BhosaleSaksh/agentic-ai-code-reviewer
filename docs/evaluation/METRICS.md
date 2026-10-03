# Evaluation Metrics & Mathematical Formulation

**Project:** Agentic AI Framework for Reliable and Evidence-Based Automated Code Review  
**Milestone:** Phase 7 — Evaluation, Benchmarking & Data Provenance  
**Date:** 2026-10-03  

---

## 1. Detection Quality Metrics

The evaluation framework maps reviewer predictions against authoritative ground-truth defects to compute a standard confusion matrix:

$$\begin{aligned}
TP &= \text{Count of correctly identified ground-truth defects} \\
FP &= \text{Count of spurious, hallucinated, or ungrounded predictions} \\
FN &= \text{Count of ground-truth defects missed by the reviewer} \\
TN &= \text{Correctly withheld non-defects (evaluated in clean file blocks)}
\end{aligned}$$

### 1.1. Precision ($P$)
Precision measures the proportion of predicted findings that correspond to genuine ground-truth defects. High precision indicates low alert noise:

$$P = \begin{cases} \frac{TP}{TP + FP} & \text{if } TP + FP > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

### 1.2. Recall ($R$) / Defect Detection Rate ($DDR$)
Recall (sensitivity) measures the proportion of genuine defects detected by the reviewer:

$$R = \begin{cases} \frac{TP}{TP + FN} & \text{if } TP + FN > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

### 1.3. $F_1$-Score
The harmonic mean of precision and recall, balancing alert cleanliness against detection completeness:

$$F_1 = \begin{cases} \frac{2 \cdot P \cdot R}{P + R} & \text{if } P + R > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

### 1.4. False Discovery / Positive Rate ($FPR$)
The proportion of reported findings that are false alarms:

$$FPR = \begin{cases} \frac{FP}{TP + FP} & \text{if } TP + FP > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

### 1.5. False Negative Rate ($FNR$) / Miss Rate
The proportion of genuine defects that slipped past the reviewer:

$$FNR = \begin{cases} \frac{FN}{TP + FN} & \text{if } TP + FN > 0 \\ 0.0 & \text{otherwise} \end{cases}$$

---

## 2. Statistical Uncertainty: Wilson Score Confidence Interval

For small to medium benchmark sample sizes ($N < 100$), standard asymptotic Gaussian approximations ($\hat{p} \pm 1.96 \sqrt{\frac{\hat{p}(1-\hat{p})}{n}}$) fail near boundaries ($0.0$ and $1.0$).

We implement the asymmetric **Wilson score interval** with continuity support at a 95% confidence level ($z = 1.95996$):

$$CI_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z \sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$

Where:
- $\hat{p} = \frac{TP}{n}$ (where $n = TP + FP$ for precision, or $n = TP + FN$ for recall)
- Boundaries are strictly clamped to $[0.0, 1.0]$.

---

## 3. Evidence Grounding & Verification Metrics

To empirically measure the specific contribution of Phase 2 evidence grounding and Phase 4 Critic verification, the following lifecycle ratios are tracked:

### 3.1. Verified Finding Rate
$$\text{Verified Rate} = \frac{\text{Verified Findings}}{\text{Total Candidate Findings}}$$

### 3.2. Critic Rejection Rate (False Alarm Suppression)
$$\text{Critic Rejection Rate} = \frac{\text{Rejected Findings by Critic}}{\text{Total Candidate Findings}}$$

### 3.3. Evidence-Grounded Finding Rate
$$\text{Evidence Grounded Rate} = \frac{\text{Verified Findings with Corroborating Evidence}}{\text{Total Verified Findings}}$$

---

## 4. Compute, Token, and Economic Cost Telemetry

To assess practical deployability (RQ5), every benchmark run records:

1. **Review Latency ($T_{\text{latency}}$):** Total wall-clock time in seconds from evaluation case submission to final finding emission.
2. **API Call Count ($N_{\text{calls}}$):** Total number of discrete external model invocations.
3. **Prompt Tokens ($K_{\text{prompt}}$):** Input tokens consumed by system instructions and diff context.
4. **Completion Tokens ($K_{\text{comp}}$):** Output tokens generated across planner, specialists, and critic.
5. **Estimated Cost ($\text{Cost}_{\text{USD}}$):** Estimated model API cost computed from standardized pricing tiers:
   $$\text{Cost} = \frac{K_{\text{prompt}} \times \$3.00 + K_{\text{comp}} \times \$15.00}{1,000,000}$$
