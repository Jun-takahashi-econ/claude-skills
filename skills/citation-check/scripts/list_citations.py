#!/usr/bin/env python3
"""Extract citations from a LaTeX/Markdown draft and list available source files.

Does NOT judge correctness -- it surfaces each citation with its claim sentence and the
candidate source files, so the model can read the sources and verify each claim against the
original text.

Usage:
    python list_citations.py --draft paper.tex --refs literature/
"""
import argparse
import os
import re


def split_sentences(text):
    return re.split(r"(?<=[.!?])\s+", text)


def extract_citations(draft_path):
    with open(draft_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    text = re.sub(r"\s+", " ", text)
    out = []
    # \citet{a,b}, \citep[see][p.2]{a}, \cite{a}, and markdown [@a]
    pat = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]+)\}|\[@([^\]]+)\]")
    sentences = split_sentences(text)
    for sent in sentences:
        for m in pat.finditer(sent):
            keys = (m.group(1) or m.group(2) or "")
            for key in [k.strip() for k in keys.split(",") if k.strip()]:
                out.append((key, sent.strip()[:240]))
    return out


def list_refs(refs_dir):
    files = []
    for root, _, names in os.walk(refs_dir):
        for n in names:
            if n.lower().endswith((".pdf", ".md", ".txt")):
                files.append(os.path.join(root, n))
    return sorted(files)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--draft", required=True)
    p.add_argument("--refs", required=True)
    args = p.parse_args()

    cites = extract_citations(args.draft)
    refs = list_refs(args.refs)

    print(f"=== {len(cites)} citation instances in {args.draft} ===")
    for key, claim in cites:
        print(f"\n[{key}]")
        print(f"  claim: {claim}")
    print(f"\n=== {len(refs)} source files in {args.refs} ===")
    for r in refs:
        print(f"  {os.path.relpath(r, args.refs)}")
    print("\nNext: map each [key] to a source file, extract its text "
          "(pdftotext file.pdf -), and verify the claim against the original.")


if __name__ == "__main__":
    main()
