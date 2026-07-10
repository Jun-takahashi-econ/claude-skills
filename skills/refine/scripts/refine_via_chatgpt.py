#!/usr/bin/env python3
"""Delegate a referee-style review of a draft to ChatGPT (OpenAI).

This is intentionally NOT Claude reviewing its own work: the memo must come from an
independent OpenAI model. Routes, in order of preference:
  1. codex CLI   -- if `codex` is on PATH (uses your ChatGPT subscription).
  2. OpenAI API  -- if OPENAI_API_KEY is set (model from --model or $OPENAI_MODEL).
If neither is available, exit non-zero so the caller does NOT fall back to Claude.

Keep your key in the environment:  export OPENAI_API_KEY=...   (never hardcode it.)

Usage:
    python refine_via_chatgpt.py --draft paper.tex --out refine_memo.md \
        --venue "short paper" --contribution "Issuer identity does not affect SC demand"
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request

BRIEF = """You are an experienced referee for an empirical economics paper. Read the draft
below and return ONLY a revision memo in the exact structure specified. Be critical and
specific; prioritize identification and whether the contribution is real and supported.

Read in this order:
1. Contribution: the one-sentence claim. Is it new vs. the cited literature, and
   interesting? Flag if unfocused or oversold.
2. Identification / validity: estimand clear? identification credible? inference and
   clustered standard errors appropriate? design checks (balance, placebo, robustness) done?
3. Evidence vs. claims: does each headline claim match the tables/figures? Flag overreach.
4. Exposition: notation, tables/figures, structure, length.

Return EXACTLY this structure (Markdown):

# Referee memo: {draft_name}
## Summary
(3-4 sentences: what the paper does, and the single most important issue)
## Major points
(numbered; each = issue -> why it matters -> concrete fix; label each BLOCKING or STRENGTHENING)
## Minor points
(numbered; exposition, notation, tables)
## What the paper can currently claim (and what it cannot, given the evidence)

Make every point actionable (name the section/table/analysis). Do not rewrite the paper.

Target venue: {venue}
Author's intended contribution: {contribution}

--- DRAFT BEGINS ---
{draft}
--- DRAFT ENDS ---
"""


def build_prompt(draft_path, venue, contribution):
    with open(draft_path, encoding="utf-8", errors="ignore") as f:
        draft = f.read()
    return BRIEF.format(draft_name=os.path.basename(draft_path),
                        venue=venue or "(unspecified)",
                        contribution=contribution or "(unspecified -- infer and state it)",
                        draft=draft)


def via_api(prompt, model):
    key = os.environ["OPENAI_API_KEY"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def via_codex(prompt):
    # codex reads the prompt and returns the model's text. Adjust flags to your version.
    res = subprocess.run(["codex", "exec", prompt], capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        sys.exit(f"codex failed: {res.stderr.strip()}")
    return res.stdout


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--draft", required=True)
    p.add_argument("--out", default="refine_memo.md")
    p.add_argument("--venue", default="")
    p.add_argument("--contribution", default="")
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.5"))
    args = p.parse_args()

    if not os.path.exists(args.draft):
        sys.exit(f"draft not found: {args.draft}")
    prompt = build_prompt(args.draft, args.venue, args.contribution)

    # Preferred route: codex CLI (uses the ChatGPT subscription, flat cost).
    # Fallback: OpenAI API (metered) if codex is not installed.
    if shutil.which("codex"):
        print("[refine] routing via codex CLI (ChatGPT subscription)", file=sys.stderr)
        memo = via_codex(prompt)
    elif os.environ.get("OPENAI_API_KEY"):
        print(f"[refine] codex not found; routing to OpenAI API (model={args.model})", file=sys.stderr)
        memo = via_api(prompt, args.model)
    else:
        sys.exit("NO_CHATGPT_ROUTE: install the codex CLI (preferred) or set OPENAI_API_KEY. "
                 "Do NOT have Claude write this memo itself -- the review must be independent.")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(memo)
    print(memo)
    print(f"\n[refine] memo written to {args.out}", file=sys.stderr)
    print("[refine] verify any literature claims (citation-check) before relying on it.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
