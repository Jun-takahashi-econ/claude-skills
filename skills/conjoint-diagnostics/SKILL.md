---
name: conjoint-diagnostics
description: >
  Run verification gates on a conjoint / survey-experiment dataset before trusting AMCE
  estimates: randomization balance, placebo AMCEs on pre-treatment covariates, profile-order
  / left-right / carryover (task-number) checks, and clustered-vs-robust SE comparison, plus
  a comprehension-failure robustness re-run. Use this skill whenever the user wants to
  validate, sanity-check, or stress-test a conjoint design or its results; asks "can we
  trust this", "is the design clean", "what can we actually say"; mentions balance, placebo,
  randomization checks, profile order, carryover, or robustness for a survey experiment.
  Trigger before reporting conjoint results as final, even if the user did not name a
  specific check.
---

# Conjoint diagnostics (verification gates)

A consistent-looking but invalid estimate survives a confident summary. These gates are a
pass/fail test suite for a conjoint design, run *before* the AMCEs are reported as final.
Each gate has a stop rule: if it fails, diagnose — do not quietly proceed.

## The gates

1. **Randomization balance.** Attribute levels should be (a) roughly uniform as randomized
   and (b) independent of respondent pre-treatment covariates (age, gender, income, etc.).
   Test by regressing each covariate on the attribute dummies; the joint test should be
   non-significant. *Stop rule:* systematic imbalance means the randomization or the data
   export is broken — fix before estimating.

2. **Placebo AMCE.** Regress a **pre-treatment** covariate (one fixed before the experiment,
   e.g. respondent gender) on the attributes as if it were the outcome. AMCEs should be ≈ 0.
   *Stop rule:* large/significant placebo effects indicate a randomization or merge problem.

3. **Profile order / left-right.** The choice should not depend on whether a profile is
   shown as A vs. B (left vs. right). Test for a position effect. *Stop rule:* a strong
   position effect means position must be controlled and reported.

4. **Carryover / fatigue (task number).** AMCEs should be stable across task number; large
   drift suggests learning or fatigue. Estimate AMCEs in early vs. late tasks and compare.
   *Stop rule:* meaningful drift must be disclosed and, if severe, modeled.

5. **Clustered vs. robust SE.** Compare respondent-clustered SEs to plain robust SEs.
   Clustered should generally be larger; report the ratio and the number of clusters.
   *Stop rule:* if clustered ≈ robust with many rows per respondent, check that clustering
   is actually applied.

6. **Comprehension-failure robustness.** If the survey has attention/comprehension checks
   (e.g. `comp_1`, `comp_2` with a known correct code), re-estimate the headline AMCEs
   excluding respondents who failed, and compare to the full sample. *Stop rule:* if the
   conclusion flips, the result is fragile and must be reported both ways. (Note: cleaning
   pipelines sometimes leave the failed-comprehension drop commented out — check.)

## Procedure

1. Confirm which columns hold the attributes, outcomes, cluster id, pre-treatment
   covariates, task-number, profile-position, and comprehension flags. Ask if unclear.
2. Run `scripts/diagnostics.py` with those column names.
3. Read the printed PASS/FLAG report. For every FLAG, state the likely cause and the
   recommended action; do not report headline AMCEs as final until the gates are addressed.

```bash
python scripts/diagnostics.py --data <long-data> \
  --attributes issuer yield_rate govt_protection network domestic_transfer_fee \
  --outcome chosen --cluster respondent_id \
  --covariates age gender income --task task_number --position profile \
  --comp comp_1:2 comp_2:2 --out <output-dir>
```

(`--comp name:correct_code` may be repeated; omit any argument that does not apply.)

## Output format

A report table: gate, statistic, threshold, PASS/FLAG, recommended action. Then a short
verdict paragraph: which gates passed, which need attention, and — given that — what the
data can and cannot currently support. Keep this honest and specific; "what can we say"
is exactly this verdict.
