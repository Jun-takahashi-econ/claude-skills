#!/usr/bin/env python3
"""Estimate AMCEs and marginal means from long-format conjoint data.

AMCE: OLS of the outcome on attribute dummies (baseline omitted), with cluster-robust
(respondent) standard errors -- the Hainmueller-Hopkins-Yamamoto (2014) estimator.
Marginal means: average outcome at each attribute level, clustered SEs (Leeper et al. 2020).

This is an INDEPENDENT re-derivation engine: run it against the same cleaned data the Stata
pipeline used and reconcile the coefficients.

Usage:
    python amce.py --data cleaned.dta \
        --attributes issuer yield_rate govt_protection network domestic_transfer_fee \
        --outcomes chosen rating --cluster respondent_id --out out/
"""
import argparse
import os
import sys
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dta":
        return pd.read_stata(path)
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    sys.exit(f"Unsupported file type: {ext}")


def amce(df, outcome, attributes, cluster):
    """OLS with attribute dummies; cluster-robust SEs on `cluster`."""
    d = df.dropna(subset=[outcome, cluster] + attributes).copy()
    # Treat attributes as categorical so the first (sorted) level is the omitted baseline.
    for a in attributes:
        d[a] = d[a].astype("category")
    rhs = " + ".join(f"C({a})" for a in attributes)
    model = smf.ols(f"{outcome} ~ {rhs}", data=d)
    res = model.fit(cov_type="cluster", cov_kwds={"groups": d[cluster]})
    rows = []
    for term in res.params.index:
        if term == "Intercept":
            continue
        # term looks like 'C(issuer)[T.level]'
        attr = term[term.find("(") + 1: term.find(")")]
        level = term[term.find("[T.") + 3: -1]
        ci = res.conf_int().loc[term]
        rows.append({
            "attribute": attr, "level": level,
            "AMCE": res.params[term], "SE": res.bse[term],
            "ci_low": ci[0], "ci_high": ci[1], "p": res.pvalues[term],
        })
    out = pd.DataFrame(rows)
    out.attrs["n_obs"] = int(res.nobs)
    out.attrs["n_clusters"] = int(d[cluster].nunique())
    return out, res


def marginal_means(df, outcome, attributes, cluster):
    """Mean outcome at each attribute level with clustered SE (one-way, level by level)."""
    rows = []
    for a in attributes:
        d = df.dropna(subset=[outcome, cluster, a]).copy()
        for level, g in d.groupby(a, observed=True):
            # clustered SE of a mean: regress outcome on constant within the level subset
            res = smf.ols(f"{outcome} ~ 1", data=g).fit(
                cov_type="cluster", cov_kwds={"groups": g[cluster]})
            rows.append({
                "attribute": a, "level": str(level),
                "marginal_mean": res.params["Intercept"], "SE": res.bse["Intercept"],
                "ci_low": res.conf_int().loc["Intercept"][0],
                "ci_high": res.conf_int().loc["Intercept"][1],
                "n": len(g),
            })
    return pd.DataFrame(rows)


def forest_plot(amce_df, outcome, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = amce_df.copy()
    labels, ys, xs, los, his = [], [], [], [], []
    y = 0
    for attr in df["attribute"].unique():
        labels.append(f"[{attr}]")
        ys.append(None)  # heading row placeholder
        xs.append(None); los.append(None); his.append(None)
        y += 1
        sub = df[df["attribute"] == attr]
        for _, r in sub.iterrows():
            labels.append(f"   {r['level']}")
            ys.append(y); xs.append(r["AMCE"]); los.append(r["ci_low"]); his.append(r["ci_high"])
            y += 1
    fig, ax = plt.subplots(figsize=(7, max(3, 0.4 * len(labels))))
    positions = list(range(len(labels)))[::-1]
    for pos, x, lo, hi in zip(positions, xs, los, his):
        if x is None:
            continue
        ax.plot([lo, hi], [pos, pos], color="0.5")
        ax.plot(x, pos, "o", color="navy")
    ax.axvline(0, ls="--", color="red", lw=1)
    ax.set_yticks(positions)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(f"AMCE on {outcome}")
    ax.set_title(f"AMCE: {outcome}")
    fig.tight_layout()
    fig.savefig(path + ".png", dpi=150)
    fig.savefig(path + ".pdf")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--attributes", nargs="+", required=True)
    p.add_argument("--outcomes", nargs="+", required=True)
    p.add_argument("--cluster", default="respondent_id")
    p.add_argument("--out", default="out")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    df = load(args.data)
    missing = [c for c in args.attributes + args.outcomes + [args.cluster] if c not in df.columns]
    if missing:
        sys.exit(f"Missing columns: {missing}\nAvailable: {list(df.columns)}")

    for outcome in args.outcomes:
        a_df, res = amce(df, outcome, args.attributes, args.cluster)
        a_df.to_csv(os.path.join(args.out, f"amce_{outcome}.csv"), index=False)
        mm = marginal_means(df, outcome, args.attributes, args.cluster)
        mm.to_csv(os.path.join(args.out, f"marginal_means_{outcome}.csv"), index=False)
        forest_plot(a_df, outcome, os.path.join(args.out, f"forest_{outcome}"))
        print(f"\n=== {outcome} (N={a_df.attrs['n_obs']}, clusters={a_df.attrs['n_clusters']}) ===")
        print(a_df.to_string(index=False,
              formatters={"AMCE": "{:.4f}".format, "SE": "{:.4f}".format,
                          "ci_low": "{:.4f}".format, "ci_high": "{:.4f}".format,
                          "p": "{:.3f}".format}))
    print(f"\nWrote tables and forest plots to {args.out}/")
    print("Reconcile amce_*.csv against the existing Stata results before trusting them.")


if __name__ == "__main__":
    main()
