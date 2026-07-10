---
name: conjoint-amce
description: >
  Estimate AMCEs (Average Marginal Component Effects) and marginal means from a long-format
  conjoint / survey-experiment dataset, with respondent-clustered standard errors, and
  reconcile against existing results. Use this skill whenever the user wants to run,
  re-run, replicate, or verify a conjoint analysis; mentions AMCE, marginal means, choice
  vs. rating outcomes, forced choice, a "conjoint experiment", or asks "what drives the
  choice / preference" in survey-experiment data; or wants an independent re-derivation of
  a Stata conjoint result in Python. Trigger even if the user just says "re-run the
  stablecoin conjoint" or "estimate the effects of the attributes".
---

# Conjoint AMCE estimation

Estimate AMCEs and marginal means following Hainmueller, Hopkins & Yamamoto (2014) and
Leeper, Hobolt & Tilley (2020), with standard errors clustered on the respondent. Produce
tidy tables and a forest plot, and — when prior results exist — reconcile against them as
an independent re-derivation.

## When to use which estimand

- **AMCE** (regression of the outcome on attribute dummies, baseline omitted): the effect
  of moving an attribute from its baseline level to another level, averaged over the
  distribution of the other attributes. Baseline-dependent; good for the headline result.
- **Marginal means**: the average outcome at each attribute level, not relative to a
  baseline. Use these for **subgroup comparisons** — differencing subgroup AMCEs can be
  misleading because it inherits the baseline. (Leeper et al. 2020.)

Report AMCEs for the main result and marginal means whenever the question is "does group X
differ from group Y".

## Inputs

A long-format dataset (one row = one profile shown within one task). Required columns:

- attribute columns (e.g. `issuer`, `yield_rate`, `govt_protection`, `network`,
  `domestic_transfer_fee`)
- outcome(s): `chosen` (0/1 forced choice) and/or `rating` (e.g. 1–7)
- cluster id: `respondent_id`

Accepts `.dta`, `.csv`, or `.parquet`. If only a wide or raw file exists, reshape to long
first and confirm the structure with the user.

## Procedure

1. Load the data and confirm the columns above exist. If attribute columns are stored as
   text, keep the labels for readable output but set an explicit baseline level per
   attribute (state which baseline you used — AMCEs depend on it).
2. Run `scripts/amce.py`, which estimates, for each requested outcome:
   - **AMCE**: OLS of the outcome on the full set of attribute dummies, with
     cluster-robust (respondent) SEs.
   - **Marginal means**: mean outcome at each level with clustered SEs.
3. Export results to tidy CSVs and a forest/coefplot figure (PNG + PDF).
4. **Reconcile** against any existing results (e.g. a Stata `AMCE_*.txt`/`.xlsx` in
   `05_result/`): match point estimates and SEs to within rounding. Report any
   discrepancy and its likely cause (different baseline, sample, clustering, or
   missing-data handling) rather than silently overwriting.

Run it like:

```bash
python scripts/amce.py --data <path-to-long-data> \
  --attributes issuer yield_rate govt_protection network domestic_transfer_fee \
  --outcomes chosen rating --cluster respondent_id --out <output-dir>
```

## Output format

For each outcome, a table with columns: attribute, level, AMCE, SE, 95% CI, p. Plus a
marginal-means table and a forest plot grouped by attribute with the baseline marked.
End with a 3–5 sentence plain-language read of which attributes move the outcome and which
do not — but keep interpretation separate from the numbers, and defer strong claims until
`conjoint-diagnostics` has passed.

## Notes

- Always cluster on `respondent_id` (each respondent contributes many rows). Note the
  number of clusters; with few clusters, flag that the asymptotics are shaky.
- This skill estimates; it does not validate the design. Run `conjoint-diagnostics` before
  trusting the estimates.
