# Technical Specification: Hyperparameter Tuning Agent Prompt Optimization

## 1. Core Logic Enhancements (`PLANNER_PROMPT`)

### A. The "Baseline Reference" Rule
**Problem:** The agent currently attempts random exploration on sparse data (low `trial_portion`) without knowing how the baseline model performs under the same constraints.
**Solution:** Add a mandatory requirement for Round 1.
* **Instruction:** "In Round 1, you **must** execute the Baseline Configuration (found in the initial Research Memory) using your chosen `trial_portion`. This establishes a 'Sparse Baseline' to calibrate your expectations. Do not change hyperparameters until this reference point is set."

### B. Progressive Research Strategy
**Problem:** The agent lacks a long-term plan, leading to fragmented trials.
**Solution:** Implement a three-phase workflow based on the `current_round`.
* **Phase 1: Screening (Rounds 1-5):** Focus on broad architecture/loss exploration with `trial_portion` 0.02–0.05 and low `epochs` (1–3). Discard configurations that fail to converge or OOM.
* **Phase 2: Refinement (Rounds 6-15):** Pick the top 2 performing architectures. Increase `trial_portion` to 0.1–0.3 and `epochs` to 10+. Fine-tune `lr` and `loss_type`.
* **Phase 3: Solidification (Rounds 16+):** Select the best candidate. Increase `trial_portion` to 0.5+ or switch to **Formal Mode** for final validation.

### C. Deep Learning Best Practices (Heuristics)
**Problem:** The agent doesn't follow standard optimization principles.
**Solution:** Add a "Heuristics Manual" section:
* **LR-Batch Scaling:** When increasing `batch_size`, consider increasing `learning_rate` (linear or square-root scaling).
* **Underfitting vs. Data:** If Training Loss is high, **increase `trial_portion`** before changing the model. Low data often prevents the optimizer from finding a stable gradient.
* **Overfitting Control:** If Training Loss improves but Denoising Score drops, you **must** increase `dropout`, `weight_decay`, or reduce `hidden_dims`. Do not add model capacity.
* **Score Reliability:** Treat score improvements of $<\pm 5\%$ at `trial_portion` < 0.1 as noise. Do not pivot based on noise; repeat the experiment with more data if unsure.

---

## 2. Rule Conflict Resolution

### A. Data Volume vs. Cross-Exploration
**Conflict:** The agent switches architectures (per the 2-round rule) even when the failure is due to insufficient data.
**Update:** "The **Cross-Exploration Rule** is suspended if the `trial_portion` is below 0.1 and the model shows signs of underfitting. In this case, your primary action must be to **double the `trial_portion`** while keeping the architecture constant to ensure the model has enough signal to learn."

---

## 3. Reflection Logic Enhancements (`REFLECTOR_PROMPT`)

### A. Gap Analysis
**Instruction:** "Explicitly calculate the 'Generalization Gap'—the difference between Training Loss trends and Denoising Score trends.
* If Gap is widening: Label as **OVERFITTING**.
* If both are stagnant: Label as **UNDERFITTING** or **INSUFFICIENT DATA**."

### B. Efficiency Benchmarking
**Instruction:** "A configuration is only 'Better' if it beats the best score. A configuration is 'Valuable' if it achieves 95% of the best score with <50% of the parameters or training time. Flag these as **High-Efficiency Discoveries**."

---

## 4. Implementation Instructions for Claude Code

1.  **Dynamic Round Context:** Modify `get_planner_user_prompt` to inject the "Current Phase" (Screening/Refinement/Solidification) based on the `current_round / max_rounds` ratio.
2.  **Constraint Enforcement:** Update the JSON output validator to ensure that if `current_round == 1`, the `model_config` and `train_config` match the baseline provided in the memory.
3.  **Config Manual Integration:** Ensure the `config_manual_data` (hyperparameter bounds) is placed immediately before the `OUTPUT FORMAT` section to keep it in the LLM's short-term memory.
4.  **Formatting:** Use LaTeX for any mathematical scaling laws (e.g., $LR_{new} = LR_{old} \times \sqrt{BS_{new}/BS_{old}}$) to ensure technical precision.

---

### Suggested Follow-up Question
Would you like me to provide the specific Python code snippets for these prompt updates, or should we focus on refining the "Config Manual" data structure first?