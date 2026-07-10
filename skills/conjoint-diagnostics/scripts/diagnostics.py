#!/usr/bin/env python3
"""Conjoint design verification gates (run BEFORE trusting AMCEs).

Implements the six gates in the conjoint-diagnostics skill, with respondent-clustered
inference where relevant. Prints a PASS/FLAG report, writes tidy CSVs + a report.md, and
ends with a "what can we say" verdict. A gate FLAGS rather than silently passing; the caller
must diagnose every FLAG before reporting headline AMCEs.

Gates:
  1. Randomization balance  (a) attribute levels ~uniform (chi-square GOF);
                            (b) attributes independent of pre-treatment covariates
                                (joint Wald test of covariate ~ attribute dummies, clustered).
  2. Placebo AMCE           pre-treatment covariate as pseudo-outcome -> AMCEs ~ 0
                            (share of individually-significant coefficients vs the 5% null).
  3. Profile order / left-right   choice independent of A/B (left/right) position.
  4. Carryover / fatigue    AMCEs stable early vs late tasks (interaction joint Wald test).
  5. Clustered vs robust SE  ratio of respondent-clustered to HC1 SEs (should be >= ~1).
  6. Comprehension robustness  headline AMCEs full sample vs comprehension-passers.

Usage (run via the project venv):
  python diagnostics.py \
    --data <long-data.csv> \
    --attributes issuer yield_rate govt_protection network domestic_transfer_fee \
    --outcome chosen --cluster respondent_id \
    --covariates sex_c age_cat_c education household_income \
    --task task_number --position profile_is_B --comp comp_1:2 comp_2:2 \
    --headline yield_rate govt_protection domestic_transfer_fee \
    --out out/diagnostics
"""
from __future__ import annotations
import argparse
import os
import sys
import itertools
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

ALPHA = 0.05


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".dta":
        return pd.read_stata(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    sys.exit(f"Unsupported file type: {ext}")


def fit(df, outcome, attrs, cluster, cov_type="cluster", extra=""):
    d = df.dropna(subset=[outcome, cluster] + attrs).copy()
    for a in attrs:
        d[a] = d[a].astype("category")
    rhs = " + ".join(f"C({a})" for a in attrs) + extra
    model = smf.ols(f"Q('{outcome}') ~ {rhs}", data=d)
    if cov_type == "cluster":
        res = model.fit(cov_type="cluster", cov_kwds={"groups": d[cluster]})
    else:
        res = model.fit(cov_type=cov_type)
    return res, d


def attr_terms(res):
    """Non-intercept, non-interaction attribute coefficient names."""
    return [t for t in res.params.index if t != "Intercept" and ":" not in t]


def joint_wald(res, terms):
    """Robust (cov already clustered) joint Wald test that the given terms are all zero."""
    names = list(res.params.index)
    R = np.zeros((len(terms), len(names)))
    for i, t in enumerate(terms):
        R[i, names.index(t)] = 1.0
    wt = res.wald_test(R, scalar=True, use_f=False)
    return float(np.squeeze(wt.statistic)), float(wt.pvalue), int(len(terms))


def gate1a_uniformity(df, attrs):
    rows = []
    for a in attrs:
        vc = df[a].value_counts().sort_index()
        obs = vc.values.astype(float)
        exp = np.full_like(obs, obs.sum() / len(obs))
        chi2 = ((obs - exp) ** 2 / exp).sum()
        p = stats.chi2.sf(chi2, len(obs) - 1)
        rows.append({"attribute": a, "k_levels": len(obs), "chi2": chi2,
                     "df": len(obs) - 1, "p": p, "min_count": int(obs.min()),
                     "max_count": int(obs.max())})
    return pd.DataFrame(rows)


def gate1c_cross_independence(df, attrs):
    """Pairwise chi-square independence of attributes (the 'independent of each other'
    half of the balance gate). Clean randomization => all pairs non-significant."""
    rows = []
    for a, b in itertools.combinations(attrs, 2):
        ct = pd.crosstab(df[a], df[b])
        chi2, p, dof, _ = stats.chi2_contingency(ct)
        rows.append({"pair": f"{a} x {b}", "chi2": chi2, "dof": dof, "p": p})
    return pd.DataFrame(rows)


def gate1b_2_balance_placebo(df, attrs, cluster, covariates):
    rows = []
    for cov in covariates:
        if cov not in df.columns:
            rows.append({"covariate": cov, "note": "absent", "joint_p": np.nan,
                         "n_sig": np.nan, "n_terms": np.nan, "n_obs": 0})
            continue
        res, d = fit(df, cov, attrs, cluster)
        terms = attr_terms(res)
        chi2, p, k = joint_wald(res, terms)
        nsig = int((res.pvalues[terms] < ALPHA).sum())
        rows.append({"covariate": cov, "n_obs": int(res.nobs), "joint_chi2": chi2,
                     "joint_df": k, "joint_p": p, "n_sig": nsig, "n_terms": k,
                     "frac_sig": nsig / k})
    return pd.DataFrame(rows)


def gate3_position(df, outcome, cluster, position):
    d = df.dropna(subset=[outcome, cluster, position]).copy()
    res = smf.ols(f"Q('{outcome}') ~ {position}", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": d[cluster]})
    coef = res.params[position]
    se = res.bse[position]
    return {"P_choose_position0": res.params["Intercept"],
            "delta_pos1_minus_pos0": coef, "SE": se, "z": coef / se,
            "p": res.pvalues[position]}


def gate4_carryover(df, outcome, attrs, cluster, task):
    d = df.dropna(subset=[outcome, cluster, task] + attrs).copy()
    median_task = d[task].median()
    d["late"] = (d[task] > median_task).astype(int)
    for a in attrs:
        d[a] = d[a].astype("category")
    rhs = "(" + " + ".join(f"C({a})" for a in attrs) + ") * late"
    res = smf.ols(f"Q('{outcome}') ~ {rhs}", data=d).fit(
        cov_type="cluster", cov_kwds={"groups": d[cluster]})
    inter = [t for t in res.params.index if ":" in t]
    chi2, p, k = joint_wald(res, inter)
    max_inter = res.params[inter].abs().max()
    return {"split": f"task<= {median_task:.0f} vs >", "joint_chi2": chi2,
            "joint_df": k, "joint_p": p, "max_abs_interaction": max_inter}, res, inter


def gate5_cluster_vs_robust(df, outcome, attrs, cluster):
    rc, d = fit(df, outcome, attrs, cluster, cov_type="cluster")
    rr, _ = fit(df, outcome, attrs, cluster, cov_type="HC1")
    terms = attr_terms(rc)
    ratio = (rc.bse[terms] / rr.bse[terms])
    return {"n_clusters": int(d[cluster].nunique()), "n_obs": int(rc.nobs),
            "mean_ratio": float(ratio.mean()), "min_ratio": float(ratio.min()),
            "max_ratio": float(ratio.max())}, ratio


def gate6_comprehension(df, outcome, attrs, cluster, comp_pass_mask, headline):
    full, _ = fit(df, outcome, attrs, cluster)
    sub_df = df[comp_pass_mask]
    sub, _ = fit(sub_df, outcome, attrs, cluster)
    terms = attr_terms(full)
    rows = []
    flips = 0
    for t in terms:
        bf, bs = full.params[t], sub.params.get(t, np.nan)
        pf, ps = full.pvalues[t], sub.pvalues.get(t, np.nan)
        sign_flip = np.sign(bf) != np.sign(bs)
        sig_flip = (pf < ALPHA) != (ps < ALPHA)
        is_headline = any(h in t for h in headline)
        if is_headline and (sign_flip or sig_flip):
            flips += 1
        rows.append({"term": t, "AMCE_full": bf, "AMCE_comp": bs,
                     "diff": bs - bf, "p_full": pf, "p_comp": ps,
                     "headline": is_headline, "sign_flip": bool(sign_flip),
                     "sig_flip": bool(sig_flip)})
    tab = pd.DataFrame(rows)
    return tab, {"n_full": int(full.nobs), "n_comp": int(sub.nobs),
                 "max_abs_diff": float(tab["diff"].abs().max()),
                 "headline_flips": int(flips)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--attributes", nargs="+", required=True)
    p.add_argument("--outcome", default="chosen")
    p.add_argument("--cluster", default="respondent_id")
    p.add_argument("--covariates", nargs="+", default=[])
    p.add_argument("--task", default="task_number")
    p.add_argument("--position", default="profile_is_B")
    p.add_argument("--comp", nargs="+", default=[], help="name:correct_code (repeatable)")
    p.add_argument("--headline", nargs="+", default=[])
    p.add_argument("--out", default="out")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    df = load(args.data)
    A, OUT, CL = args.attributes, args.outcome, args.cluster
    report = []  # (gate, statistic, threshold, verdict, action)

    # ---- Gate 1a: uniformity --------------------------------------------------------
    g1a = gate1a_uniformity(df, A)
    g1a.to_csv(os.path.join(args.out, "gate1a_uniformity.csv"), index=False)
    flag1a = (g1a["p"] < ALPHA).any()
    report.append(("1a Level uniformity", f"min chi2-GOF p={g1a['p'].min():.3f}",
                   "p>0.05 for all attrs", "FLAG" if flag1a else "PASS",
                   "investigate non-uniform attribute" if flag1a else "-"))

    # ---- Gate 1c: attribute cross-independence --------------------------------------
    g1c = gate1c_cross_independence(df, A)
    g1c.to_csv(os.path.join(args.out, "gate1c_cross_independence.csv"), index=False)
    n_pairs = len(g1c)
    bonf = ALPHA / n_pairs
    n_pair_sig = int((g1c["p"] < ALPHA).sum())
    flag1c = (g1c["p"] < bonf).any()  # flag only if it survives Bonferroni
    report.append(("1c Attribute cross-independence",
                   f"min pair p={g1c['p'].min():.3f}; {n_pair_sig}/{n_pairs} pairs p<.05",
                   f"none below Bonferroni {bonf:.3f}", "FLAG" if flag1c else "PASS",
                   "investigate dependent attribute pair" if flag1c else "-"))

    # ---- Gate 1b + 2: balance / placebo --------------------------------------------
    g12 = gate1b_2_balance_placebo(df, A, CL, args.covariates)
    g12.to_csv(os.path.join(args.out, "gate1b2_balance_placebo.csv"), index=False)
    g12v = g12.dropna(subset=["joint_p"])
    n_cov = len(g12v)
    n_bal_fail = int((g12v["joint_p"] < ALPHA).sum())
    total_terms = int(g12v["n_terms"].sum())
    total_sig = int(g12v["n_sig"].sum())
    frac_sig_overall = total_sig / total_terms if total_terms else float("nan")
    # Expect ~ALPHA of joint tests significant by chance; flag if clearly excessive.
    exp_bal = ALPHA * n_cov
    flag1b = n_bal_fail > max(1, exp_bal + 2 * np.sqrt(max(exp_bal, 1e-9)))
    report.append(("1b Balance (cov~attr joint)",
                   f"{n_bal_fail}/{n_cov} covariates joint-sig (exp ~{exp_bal:.1f})",
                   "near the 5% chance rate", "FLAG" if flag1b else "PASS",
                   "inspect imbalanced covariate" if flag1b else "-"))
    flag2 = frac_sig_overall > ALPHA * 2  # placebo coefficients far above 5% null
    report.append(("2 Placebo AMCE",
                   f"{total_sig}/{total_terms} placebo coefs sig ({frac_sig_overall:.3f})",
                   f"~{ALPHA:.2f} false-positive rate", "FLAG" if flag2 else "PASS",
                   "diagnose merge/randomization" if flag2 else "-"))

    # ---- Gate 3: profile order / left-right -----------------------------------------
    g3 = gate3_position(df, OUT, CL, args.position)
    pd.DataFrame([g3]).to_csv(os.path.join(args.out, "gate3_position.csv"), index=False)
    flag3 = g3["p"] < ALPHA
    report.append(("3 Profile order (left-right)",
                   f"delta={g3['delta_pos1_minus_pos0']:+.4f} (p={g3['p']:.3f})",
                   "no position preference", "FLAG" if flag3 else "PASS",
                   "control for & report position" if flag3 else "-"))

    # ---- Gate 4: carryover / fatigue ------------------------------------------------
    g4, g4res, g4inter = gate4_carryover(df, OUT, A, CL, args.task)
    pd.DataFrame([g4]).to_csv(os.path.join(args.out, "gate4_carryover.csv"), index=False)
    flag4 = g4["joint_p"] < ALPHA
    report.append(("4 Carryover (task-number)",
                   f"interaction joint p={g4['joint_p']:.3f}, max|int|={g4['max_abs_interaction']:.4f}",
                   "no early/late AMCE drift", "FLAG" if flag4 else "PASS",
                   "disclose/model drift" if flag4 else "-"))

    # ---- Gate 5: clustered vs robust SE ---------------------------------------------
    g5, g5ratio = gate5_cluster_vs_robust(df, OUT, A, CL)
    pd.DataFrame([g5]).to_csv(os.path.join(args.out, "gate5_se_ratio.csv"), index=False)
    flag5 = g5["mean_ratio"] < 1.0  # clustered should be >= robust
    report.append(("5 Clustered vs robust SE",
                   f"mean ratio={g5['mean_ratio']:.2f} (min {g5['min_ratio']:.2f}), G={g5['n_clusters']}",
                   "clustered >= robust", "FLAG" if flag5 else "PASS",
                   "check clustering applied" if flag5 else "-"))

    # ---- Gate 6: comprehension robustness -------------------------------------------
    comp_flag = "PASS"; g6sum = {}
    if args.comp:
        mask = pd.Series(True, index=df.index)
        for spec in args.comp:
            name, code = spec.split(":")
            mask &= (df[name] == float(code))
        g6tab, g6sum = gate6_comprehension(df, OUT, A, CL, mask, args.headline)
        g6tab.to_csv(os.path.join(args.out, "gate6_comprehension.csv"), index=False)
        flag6 = g6sum["headline_flips"] > 0
        comp_flag = "FLAG" if flag6 else "PASS"
        report.append(("6 Comprehension robustness",
                       f"headline flips={g6sum['headline_flips']}, max|diff|={g6sum['max_abs_diff']:.4f} "
                       f"(n {g6sum['n_full']}->{g6sum['n_comp']})",
                       "no headline sign/sig flip", comp_flag,
                       "report both ways" if flag6 else "-"))

    # ---- report ----------------------------------------------------------------------
    rep = pd.DataFrame(report, columns=["gate", "statistic", "threshold", "verdict", "action"])
    rep.to_csv(os.path.join(args.out, "diagnostics_report.csv"), index=False)
    print("\n================ CONJOINT DIAGNOSTICS REPORT ================")
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(rep.to_string(index=False))
    n_flag = int((rep["verdict"] == "FLAG").sum())
    print(f"\n{len(rep)} gates run | {n_flag} FLAG | {len(rep)-n_flag} PASS")
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("# Diagnostics report\n\n")
        cols = list(rep.columns)
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("| " + " | ".join("---" for _ in cols) + " |\n")
        for _, r in rep.iterrows():
            f.write("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in cols) + " |\n")
        f.write(f"\n{len(rep)} gates run | {n_flag} FLAG | {len(rep)-n_flag} PASS\n")
    print(f"\nWrote tables + report.md to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
