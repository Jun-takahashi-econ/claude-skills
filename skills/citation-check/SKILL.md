---
name: citation-check
description: >
  Verify every citation and characterization of cited work in a draft against the original
  source text in the reference library, never against model memory. Use this skill whenever
  the user is writing or revising a paper and wants to check citations, catch hallucinated
  or mischaracterized references, confirm a cited result actually says what the draft claims,
  or audit a bibliography before submission. Trigger whenever a .tex/.md draft cites prior
  work and correctness of those citations matters -- even if the user only says "check my
  references" or "make sure the lit review is right".
---

# Citation check (source verification)

Citing from memory produces plausible references that do not say what is claimed. This skill
checks each citation in a draft against the **original source text** held in the reference
library (the project `literature/` folder, or a configured `reference/` directory). A claim
that cannot be confirmed against a source is flagged, not approved.

## Procedure

1. Locate the draft (`.tex` or `.md`) and the reference library.
2. Run `scripts/list_citations.py` to extract every `\citet`/`\citep`/`\cite` key together
   with the sentence that makes the claim, and to list the available source files.
3. For each citation:
   - Map the bib key to its source file in the library. If no source file exists, mark
     **MISSING SOURCE** and do not vouch for the claim.
   - If the source is a PDF, extract text first (`pdftotext source.pdf -` or an existing
     `.md` conversion). Read the relevant passage.
   - Compare the draft's claim to the source. Classify as **SUPPORTED**,
     **MISCHARACTERIZED** (source exists but does not support the specific claim), or
     **MISSING SOURCE**.
4. Produce the report table. For anything not SUPPORTED, quote the relevant source sentence
   (briefly) and state what the draft should say instead.

```bash
python scripts/list_citations.py --draft paper.tex --refs literature/
```

## Output format

ALWAYS use this table:

| bib key | claim (short) | source found? | verdict | note |
|---|---|---|---|---|

Verdicts: SUPPORTED / MISCHARACTERIZED / MISSING SOURCE. End with a count and an explicit
list of the citations that must be fixed before the draft is presented or submitted.

## Rules

- A result provable from definitions alone (not attributed to a specific paper) is exempt
  unless the draft attributes a specific claim/version to a specific source.
- Never upgrade a verdict to SUPPORTED from memory. If the source text is unavailable, the
  verdict is MISSING SOURCE and the draft must flag it.
- Keep any quoted source text short and clearly marked; the goal is verification, not
  reproduction.
