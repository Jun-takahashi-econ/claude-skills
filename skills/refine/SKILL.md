---
name: refine
description: >
  Get a referee-style, prioritized, actionable revision memo for an empirical economics
  draft -- but ALWAYS by delegating the review to an external ChatGPT (OpenAI) agent, never
  by writing the memo yourself. Claude packages the draft and context, dispatches to ChatGPT,
  then verifies and integrates the returned memo. Use this skill whenever the user wants
  feedback on a paper or section, a referee report, a critical read, a "what's weak here"
  assessment, or help deciding whether the contribution is real and supported. Trigger on
  "review my draft", "referee this", "what can we actually say", "is this submittable", or
  "give me revisions". Do not rewrite the paper -- return the memo so the author keeps
  judgment.
---

# Refine (referee memo, delegated to ChatGPT)

The review MUST come from an **independent ChatGPT (OpenAI) agent**, not from Claude. An
independent reviewer that did not draft the paper catches what a self-review smooths over.
Claude's job here is to package the draft, dispatch it to ChatGPT, then verify and present
the returned memo -- not to author the critique.

## Hard rule

Do not generate the referee memo yourself. If no ChatGPT route is available (no
`OPENAI_API_KEY` and no `codex` CLI), STOP and tell the user how to enable one. Do not
silently substitute Claude's own review -- that defeats the purpose of an independent check.

## Procedure

1. Locate the draft (`.tex`/`.md`) and note the target venue and the intended one-sentence
   contribution (ask if unstated -- the reviewer needs them).
2. Dispatch to ChatGPT with `scripts/refine_via_chatgpt.py`. It embeds the referee brief
   (below) and the draft, calls OpenAI, and returns the memo.
   ```bash
   python scripts/refine_via_chatgpt.py --draft paper.tex --out refine_memo.md \
     --venue "short paper / SBI report" --contribution "<one sentence>"
   ```
   Route selection: uses the `codex` CLI (ChatGPT-subscription-backed) if present; else the
   OpenAI API if `OPENAI_API_KEY` is set. `codex` is the chosen default (flat subscription
   cost). For the API fallback, set `OPENAI_MODEL` to choose the model (latest flagship is
   GPT-5.5).
3. **Verify before presenting.** Read the returned memo. Check any claim it makes about the
   literature against sources (run `citation-check`); ChatGPT can assert novelty or priority
   from memory, and those must not be passed through unverified.
4. Present the memo as-is (clearly attributed to the ChatGPT reviewer), plus a short note of
   any point you could not verify. Integrate into the paper only when the user picks points
   to act on, one at a time.

## Referee brief (what ChatGPT is asked to produce)

The script instructs ChatGPT to read in this order and return a structured memo:

1. **Contribution** -- the one-sentence claim; is it new vs. the cited literature, and
   interesting? Flag if unfocused or oversold.
2. **Identification / validity** -- estimand clear? identification credible? inference and
   clustered SEs appropriate? design checks (balance, placebo, robustness) done? This is
   where empirical papers fail.
3. **Evidence vs. claims** -- does each headline claim match the tables/figures?
4. **Exposition** -- notation, tables/figures, structure, length.

Output format ChatGPT must follow:

```
# Referee memo: [draft name]
## Summary (3-4 sentences; what it does + the single most important issue)
## Major points (numbered; issue -> why it matters -> concrete fix; label BLOCKING or STRENGTHENING)
## Minor points (numbered; exposition, notation, tables)
## What the paper can currently claim (and what it cannot, given the evidence)
```

## Notes

- Keep the OpenAI API key in the environment (`OPENAI_API_KEY`); never hardcode it.
- This skill produces feedback, not a rewrite. The author keeps judgment.
