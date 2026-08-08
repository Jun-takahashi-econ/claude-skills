#!/usr/bin/env python3
"""Enrich a converted Markdown file's YAML front matter from Crossref and emit a
local BibTeX sidecar.

Part of the `literature-sync` skill. Runs *after* `gemini-pdf` has produced the
`.md`. It never touches the source PDF and never writes to the central
reference library (`GEMINI_PDF_REFERENCE_DIR`) — that path stays opt-in via
`sync_literature.sh --bib`.

Design notes
------------
* Volume / issue / pages are *not* asked of the LLM. They are frequently absent
  from the printed PDF (accepted versions, working papers, preprints) and are
  exactly the numeric fields most prone to OCR damage. The DOI in the front
  matter is used to fetch them from Crossref, which is authoritative.
* Crossref wins on conflict; every overwritten value is logged so the diff is
  auditable.
* Without a DOI, no network call is made by default: a best-effort `.bib` is
  still written from the front matter and clearly marked as unverified.
  `--search-fallback` enables a title-based Crossref lookup that is only
  accepted above a similarity threshold and is always marked for review.
* Idempotent. A `crossref:` marker in the front matter records the outcome;
  re-runs skip already-enriched files unless `--refresh` is passed.
* Network failure is non-fatal: the `.md` is left untouched and the exit code
  stays 0 so a Crossref outage never fails a conversion run.
* BibTeX keys are *sanitized* file names, not raw ones: spaces, commas and dots
  are illegal or fatal in a key (`@article{Senhu, Yi and Yang 2023 PRPR,` breaks
  the parser at the comma). The link back to the source file is preserved in the
  `file` field instead, which keeps the key -> source mapping that
  `citation-check` relies on. Non-ASCII letters are kept by default (valid in
  biber / upBibTeX); `--ascii-keys` forces a legacy-bibtex-safe key.

Usage
-----
    python3 enrich_metadata.py --md literature/md/smith-2020-aer.md \
        [--bib-dir literature/bib] [--mailto you@example.org]

    python3 enrich_metadata.py --batch --md-dir literature/md \
        [--bib-dir literature/bib] [--search-fallback] [--refresh]

Exit codes: 0 = done (including "skipped" and "network unavailable"),
            1 = usage / filesystem error.
"""

import argparse
import datetime as _dt
import difflib
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

__version__ = "0.2.1"

CROSSREF_API = "https://api.crossref.org/works"
DEFAULT_TIMEOUT = 20
DEFAULT_SIM_THRESHOLD = 0.90

# Front matter keys this script manages. Anything else already in the block is
# preserved verbatim and in its original position.
MANAGED_KEYS = [
    "title", "authors", "year", "journal", "volume", "number",
    "pages", "publisher", "doi", "crossref",
]

# Crossref work type -> BibTeX entry type.
TYPE_MAP = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "book-chapter": "incollection",
    "book-part": "incollection",
    "report": "techreport",
    "report-component": "techreport",
    "dissertation": "phdthesis",
    "posted-content": "misc",
    "dataset": "misc",
    "component": "misc",
}


# --------------------------------------------------------------------------
# Front matter
# --------------------------------------------------------------------------

FM_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def read_front_matter(md_path):
    """Return (meta, block_lines, start, end, lines).

    `start` is the index of the opening `---`, `end` the index of the closing
    `---`. Returns (None, ...) when there is no parsable block. Deliberately
    stdlib-only, matching the upstream gemini-pdf parser's format assumptions:
    a leading `---` block of plain `key: value` lines.
    """
    try:
        with open(md_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None, [], -1, -1, []

    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None, [], -1, -1, lines

    end = -1
    for j in range(i + 1, min(i + 40, len(lines))):
        if lines[j].strip() == "---":
            end = j
            break
    if end == -1:
        return None, [], -1, -1, lines

    meta = {}
    for line in lines[i + 1:end]:
        m = FM_LINE.match(line)
        if not m:
            continue
        key = m.group(1).lower()
        value = m.group(2).strip().strip('"').strip("'")
        if value:
            meta[key] = value
    return meta, lines[i + 1:end], i, end, lines


def split_authors(value):
    parts = re.split(r";| and ", value or "")
    return [p.strip() for p in parts if p.strip()]


def render_front_matter(block_lines, updates):
    """Merge `updates` into an existing front matter block.

    Existing managed keys are updated in place (order preserved); unmanaged
    lines are kept verbatim; new managed keys are appended in MANAGED_KEYS
    order after the last recognised line.
    """
    out = []
    seen = set()
    for line in block_lines:
        m = FM_LINE.match(line)
        if not m:
            out.append(line)
            continue
        key = m.group(1).lower()
        if key in updates:
            out.append(f"{key}: {updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key in MANAGED_KEYS:
        if key in updates and key not in seen:
            out.append(f"{key}: {updates[key]}")
    return out


def write_front_matter(md_path, lines, start, end, new_block):
    new_lines = lines[:start + 1] + new_block + lines[end:]
    tmp = md_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(new_lines) + "\n")
    os.replace(tmp, md_path)


# --------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------

def _user_agent(mailto):
    base = f"literature-sync/{__version__} (https://github.com/Jun-takahashi-econ/claude-skills"
    if mailto:
        base += f"; mailto:{mailto}"
    return base + ") python-urllib"


def _get_json(url, mailto, timeout):
    """GET JSON with one retry on 429/5xx. Returns None on any failure."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _user_agent(mailto),
        "Accept": "application/json",
    })
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(2)
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            if attempt == 1:
                time.sleep(1)
                continue
            return None
    return None


def clean_doi(raw):
    if not raw:
        return ""
    doi = raw.strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    return doi.strip().rstrip(".")


def fetch_by_doi(doi, mailto, timeout):
    url = f"{CROSSREF_API}/{urllib.parse.quote(doi, safe='')}"
    data = _get_json(url, mailto, timeout)
    if not data or "message" not in data:
        return None
    return data["message"]


def _normalize_title(text):
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def search_by_title(title, authors, mailto, timeout, threshold):
    """Fuzzy Crossref lookup. Returns (item, score) or (None, 0.0).

    Never trusted silently: the caller marks the result for manual review.
    """
    if not title:
        return None, 0.0
    query = title
    if authors:
        query += " " + " ".join(authors[:2])
    url = (f"{CROSSREF_API}?"
           + urllib.parse.urlencode({"query.bibliographic": query, "rows": 5}))
    data = _get_json(url, mailto, timeout)
    if not data:
        return None, 0.0
    items = data.get("message", {}).get("items", []) or []
    best, best_score = None, 0.0
    target = _normalize_title(title)
    for item in items:
        cand = (item.get("title") or [""])[0]
        score = difflib.SequenceMatcher(None, target, _normalize_title(cand)).ratio()
        if score > best_score:
            best, best_score = item, score
    if best_score >= threshold:
        return best, best_score
    return None, best_score


def normalize_item(item):
    """Crossref work -> flat metadata dict."""
    meta = {}

    titles = item.get("title") or []
    if titles:
        meta["title"] = strip_markup(titles[0])

    authors = []
    for a in item.get("author") or []:
        if a.get("family"):
            given = (a.get("given") or "").strip()
            authors.append(f"{given} {a['family']}".strip())
        elif a.get("name"):
            # Corporate author: brace it so it survives the front matter
            # round-trip and is never split into "Family, Given".
            authors.append("{" + a["name"].strip() + "}")
    if authors:
        meta["authors"] = authors

    year = ""
    for field in ("issued", "published-print", "published-online", "created"):
        parts = (item.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    if year:
        meta["year"] = year

    container = item.get("container-title") or []
    if container:
        meta["journal"] = strip_markup(container[0])
    else:
        insts = item.get("institution") or []
        if isinstance(insts, list) and insts:
            name = insts[0].get("name") if isinstance(insts[0], dict) else str(insts[0])
            if name:
                meta["journal"] = strip_markup(name)
        elif item.get("group-title"):
            meta["journal"] = strip_markup(item["group-title"])

    for src, dst in (("volume", "volume"), ("issue", "number"),
                     ("publisher", "publisher")):
        val = item.get(src)
        if val:
            meta[dst] = strip_markup(str(val))

    page = item.get("page")
    if page:
        meta["pages"] = re.sub(r"\s*[-–—]+\s*", "--", str(page).strip())

    if item.get("DOI"):
        meta["doi"] = item["DOI"]

    meta["_type"] = item.get("type", "")
    subtype = item.get("subtype", "")
    if subtype:
        meta["_subtype"] = subtype
    return meta


# --------------------------------------------------------------------------
# BibTeX
# --------------------------------------------------------------------------

def strip_markup(text):
    """Remove HTML/JATS tags and unescape entities. Crossref titles carry both."""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def bib_escape(value):
    """Make a value safe inside a BibTeX field.

    Braces and backslashes are dropped rather than escaped so the surrounding
    `{...}` can never become unbalanced; the handful of characters BibTeX
    treats as special are escaped.
    """
    value = str(value).replace("\\", "").replace("{", "").replace("}", "")
    for ch in ("&", "%", "#", "_", "$"):
        value = value.replace(ch, "\\" + ch)
    return value.strip()


def bib_escape_path(value):
    """Escape a file path for the non-standard `file` field.

    Tools such as JabRef and Zotero read this field literally, so LaTeX-escaping
    `_` or `&` would corrupt the path. Only the characters that would break
    brace matching are removed; backslashes become forward slashes so a path
    written on Windows still resolves.
    """
    return (str(value).replace("\\", "/")
            .replace("{", "").replace("}", "").strip())


PARTICLES = ["van der", "van den", "van", "de la", "della", "de", "di", "del", "el", "ter"]


# --- BibTeX keys -----------------------------------------------------------
# A key may not contain whitespace, a comma, or braces. A comma is fatal: it
# terminates the key and the rest of the entry becomes a parse error. Real
# library filenames routinely contain all three ("Senhu, Yi and Yang 2023
# PRPR.pdf"), so the key is derived from the filename rather than copied.

KEY_BAD = re.compile(r"[^\w:\-]", re.UNICODE)     # \w keeps letters (any script) + digits + _
KEY_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
BIB_KEY_IN_FILE = re.compile(r"^@\w+\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)


def sanitize_key(name, ascii_only=False):
    """File name -> a BibTeX-legal citation key.

    Default keeps non-ASCII letters, which biber and upBibTeX accept and which
    keeps Japanese sources citable as themselves. `ascii_only` drops them for
    legacy bibtex and falls back to a hashed key when nothing citable is left.
    """
    original = name
    lossy = False
    if ascii_only:
        name = unicodedata.normalize("NFKD", name)
        stripped = name.encode("ascii", "ignore").decode("ascii")
        lossy = KEY_HAS_LETTER.search(name) and stripped != name
        name = stripped
    key = KEY_BAD.sub("-", name)
    key = re.sub(r"-{2,}", "-", key).strip("-_")
    if not KEY_HAS_LETTER.search(key):
        digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:4]
        key = re.sub(r"-{2,}", "-", f"ref-{key}-{digest}").strip("-")
    elif lossy:
        # Letters were dropped, so the remainder is not reliably distinctive
        # ("北 荻野 辻村 DP" -> "DP"). A digest of the original name keeps the key
        # unique and stable across runs rather than order-dependent.
        key += "-" + hashlib.sha1(original.encode("utf-8")).hexdigest()[:4]
    return key or "ref-unknown"


def collect_existing_keys(bib_dir, exclude=None):
    """Every key already present in the .bib tree, minus the file we're rewriting.

    Excluding our own target keeps re-runs idempotent: a paper does not acquire
    a `-2` suffix just because its previous entry is still on disk.
    """
    keys = set()
    if not bib_dir or not os.path.isdir(bib_dir):
        return keys
    exclude = os.path.abspath(exclude) if exclude else None
    for root, _dirs, names in os.walk(bib_dir):
        for n in names:
            if not n.endswith(".bib"):
                continue
            path = os.path.join(root, n)
            if exclude and os.path.abspath(path) == exclude:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    keys.update(BIB_KEY_IN_FILE.findall(fh.read()))
            except OSError:
                continue
    return keys


def unique_key(base, taken):
    """Disambiguate against keys already in use, so a concatenated .bib is valid."""
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def format_author(name):
    """`Given Family` -> `Family, Given`, keeping multi-word particles together."""
    name = name.strip()
    if not name:
        return ""
    if name.startswith("{") and name.endswith("}"):   # corporate author
        return "{" + bib_escape(name[1:-1]) + "}"
    if "," in name:                      # already in BibTeX order
        return bib_escape(name)
    parts = name.split()
    if len(parts) == 1:
        return "{" + bib_escape(parts[0]) + "}"
    for particle in sorted(PARTICLES, key=len, reverse=True):
        p_parts = particle.split()
        n = len(p_parts)
        for i in range(1, len(parts) - n + 1):
            if " ".join(parts[i:i + n]).lower() == particle and i + n < len(parts):
                family = " ".join(parts[i:])
                given = " ".join(parts[:i])
                return "{" + bib_escape(family) + "}, " + bib_escape(given)
    return f"{bib_escape(parts[-1])}, {bib_escape(' '.join(parts[:-1]))}"


def entry_type(meta):
    cr_type = meta.get("_type", "")
    if cr_type in TYPE_MAP:
        etype = TYPE_MAP[cr_type]
        if etype == "misc" and meta.get("_subtype") == "preprint":
            return "misc"
        return etype
    journal = (meta.get("journal") or "").lower()
    if not journal:
        return "misc"
    # "Proceedings" alone is not a conference signal — "Proceedings of the
    # National Academy of Sciences" is a journal. Require an explicit conference
    # word or a known conference name.
    if "conference" in journal or any(
            k in journal for k in ("neurips", "icml", "iclr", "aaai", "aistats",
                                   "conf. proc", "conference proceedings")):
        return "inproceedings"
    if any(k in journal for k in ("arxiv", "nber", "working paper", "ssrn",
                                  "discussion paper", "mimeo")):
        return "techreport"
    return "article"


def build_bib(key, meta, provenance, file_name=None):
    etype = entry_type(meta)
    fields = []

    authors = meta.get("authors") or []
    if isinstance(authors, str):
        authors = split_authors(authors)
    if authors:
        fields.append(("author", " and ".join(format_author(a) for a in authors)))

    if meta.get("title"):
        fields.append(("title", "{" + bib_escape(meta["title"]) + "}"))

    venue = meta.get("journal", "")
    if venue:
        if etype == "article":
            fields.append(("journal", bib_escape(venue)))
        elif etype == "inproceedings":
            fields.append(("booktitle", bib_escape(venue)))
        elif etype == "incollection":
            fields.append(("booktitle", bib_escape(venue)))
        elif etype in ("techreport", "phdthesis"):
            fields.append(("institution", bib_escape(venue)))
        else:
            fields.append(("howpublished", bib_escape(venue)))

    for src, dst in (("year", "year"), ("volume", "volume"),
                     ("number", "number"), ("pages", "pages")):
        if meta.get(src):
            fields.append((dst, bib_escape(meta[src])))

    if meta.get("publisher") and etype in ("book", "incollection"):
        fields.append(("publisher", bib_escape(meta["publisher"])))

    if meta.get("doi"):
        fields.append(("doi", bib_escape(meta["doi"])))

    # The key is sanitized, so `file` is what still ties the entry to the source
    # PDF on disk (relative to the pdf/ root, mirroring the md/ tree).
    fields.append(("file", bib_escape_path(file_name or f"{key}.pdf")))

    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    header = (f"% {provenance}\n"
              f"% generated by literature-sync/enrich_metadata.py "
              f"{_dt.date.today().isoformat()}\n")
    return f"{header}@{etype}{{{key},\n{body},\n}}\n"


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Per-file driver
# --------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def relative_name(md_path, args):
    """Path of this paper relative to the md tree, without the .md extension."""
    rel = os.path.basename(md_path)
    if args.md_dir and os.path.isdir(args.md_dir):
        candidate = os.path.relpath(os.path.abspath(md_path),
                                    os.path.abspath(args.md_dir))
        if not candidate.startswith(os.pardir):
            rel = candidate
    return rel[:-3] if rel.endswith(".md") else rel


def enrich_one(md_path, args, taken=None):
    """Returns 'enriched' | 'unverified' | 'rebuilt' | 'skipped' | 'offline' | 'nofm'."""
    rel = relative_name(md_path, args)
    bib_target = bib_path_for(md_path, args) if args.bib_dir else None
    if taken is None:
        taken = collect_existing_keys(args.bib_dir, exclude=bib_target)
    key = unique_key(sanitize_key(os.path.basename(rel), args.ascii_keys), taken)
    taken.add(key)
    source_pdf = rel + ".pdf"
    meta, block, start, end, lines = read_front_matter(md_path)

    if meta is None:
        log(args, f"  no front matter: {md_path}")
        if bib_target:
            if not os.path.exists(bib_target) or args.refresh:
                write_text(bib_target,
                           build_bib(key, {"title": os.path.basename(rel)},
                                     "source: filename only — UNVERIFIED",
                                     source_pdf))
        return "nofm"

    merged = {k: v for k, v in meta.items() if not k.startswith("_")}
    if "authors" in merged:
        merged["authors"] = split_authors(merged["authors"])

    marker = meta.get("crossref", "")
    if marker and not args.refresh and (DATE_RE.match(marker) or not args.search_fallback):
        # Already queried. Don't re-query — but a missing .bib still has to be
        # rebuilt, so deleting literature/bib/ and re-running restores it.
        if bib_target and not os.path.exists(bib_target):
            write_text(bib_target, build_bib(
                key, merged, f"source: front matter (crossref: {marker})", source_pdf))
            log(args, f"  bib rebuilt -> {bib_target}  (key: {key})")
            return "rebuilt"
        log(args, f"  skip (already processed: {marker}): {key}")
        return "skipped"

    doi = clean_doi(meta.get("doi", ""))
    item, score, provenance = None, 0.0, ""

    if doi:
        item = fetch_by_doi(doi, args.mailto, args.timeout)
        if item is None:
            if not network_ok(args):
                log(args, f"  Crossref unreachable, left untouched: {key}")
                return "offline"
            provenance = f"source: front matter — DOI {doi} not found in Crossref, UNVERIFIED"
        else:
            provenance = f"source: Crossref ({doi})"
    elif args.search_fallback:
        item, score = search_by_title(meta.get("title", ""),
                                      split_authors(meta.get("authors", "")),
                                      args.mailto, args.timeout, args.threshold)
        if item is not None:
            provenance = (f"source: Crossref title search "
                          f"(similarity {score:.2f}) — VERIFY BEFORE CITING")
        else:
            provenance = (f"source: front matter — no DOI, no confident Crossref "
                          f"match (best {score:.2f}), UNVERIFIED")
    else:
        provenance = "source: front matter — no DOI, UNVERIFIED"

    status = "unverified"
    updates = {}
    if item is not None:
        cr = normalize_item(item)
        for k, v in cr.items():
            if k.startswith("_"):
                merged[k] = v
                continue
            old = merged.get(k)
            old_str = "; ".join(old) if isinstance(old, list) else (old or "")
            new_str = "; ".join(v) if isinstance(v, list) else str(v)
            if old_str and _normalize_title(old_str) != _normalize_title(new_str):
                log(args, f"  [{key}] {k}: '{old_str}' -> '{new_str}' (Crossref)")
            if not old_str or old_str != new_str:
                updates[k] = new_str
            merged[k] = v
        updates["crossref"] = (_dt.date.today().isoformat() if doi
                               else f"search:{score:.2f}")
        status = "enriched" if doi else "unverified"
    else:
        updates["crossref"] = "not-found" if doi else "no-doi"

    if not args.no_md_update and start >= 0:
        new_block = render_front_matter(block, updates)
        if new_block != block:
            write_front_matter(md_path, lines, start, end, new_block)

    if bib_target:
        if not os.path.exists(bib_target) or args.refresh or item is not None:
            write_text(bib_target, build_bib(key, merged, provenance, source_pdf))
            log(args, f"  bib -> {bib_target}  (key: {key})")

    return status


def network_ok(args):
    """Distinguish 'DOI genuinely absent' from 'no network' with one cheap probe."""
    return _get_json(f"{CROSSREF_API}?rows=0", args.mailto, min(args.timeout, 8)) is not None


def bib_path_for(md_path, args):
    """Mirror the md tree's subfolder structure under --bib-dir."""
    return os.path.join(args.bib_dir, relative_name(md_path, args) + ".bib")


def log(args, msg):
    if not args.quiet:
        print(msg, file=sys.stderr)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Enrich converted Markdown front matter from Crossref and "
                    "write a local BibTeX sidecar.")
    p.add_argument("--md", help="single converted Markdown file")
    p.add_argument("--batch", action="store_true", help="process every .md under --md-dir")
    p.add_argument("--md-dir", default=os.environ.get("LIT_OUT_DIR", "literature/md"),
                   help="Markdown tree (default: literature/md)")
    p.add_argument("--bib-dir", default=os.environ.get("LIT_BIB_DIR", "literature/bib"),
                   help="where .bib sidecars are written; empty string disables")
    p.add_argument("--mailto", default=os.environ.get("CROSSREF_MAILTO", ""),
                   help="contact address for the Crossref polite pool")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--threshold", type=float, default=DEFAULT_SIM_THRESHOLD,
                   help="title-similarity cutoff for --search-fallback (default 0.90)")
    p.add_argument("--search-fallback", action="store_true",
                   help="when no DOI is present, try a title search (flagged for review)")
    p.add_argument("--ascii-keys", action="store_true",
                   help="force ASCII-only BibTeX keys for legacy bibtex "
                        "(default keeps non-ASCII letters, valid in biber/upBibTeX)")
    p.add_argument("--refresh", action="store_true",
                   help="re-query even if the file carries a crossref: marker")
    p.add_argument("--no-md-update", action="store_true",
                   help="write the .bib only; leave the Markdown untouched")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if not args.md and not args.batch:
        p.error("provide --md FILE or --batch")

    targets = []
    if args.md:
        if not os.path.isfile(args.md):
            print(f"ERROR: no such file: {args.md}", file=sys.stderr)
            return 1
        targets = [args.md]
    else:
        if not os.path.isdir(args.md_dir):
            print(f"ERROR: no such directory: {args.md_dir}", file=sys.stderr)
            return 1
        for root, _dirs, names in os.walk(args.md_dir):
            for n in sorted(names):
                if n.endswith(".md"):
                    targets.append(os.path.join(root, n))

    tally = {}
    # One shared registry so keys stay unique across the whole library, which
    # matters as soon as the .bib files are concatenated for a LaTeX build.
    taken = collect_existing_keys(args.bib_dir) if args.batch else None
    if taken is not None:
        taken -= {sanitize_key(os.path.basename(relative_name(t, args)),
                               args.ascii_keys) for t in targets}
    for i, path in enumerate(targets):
        status = enrich_one(path, args, taken)
        tally[status] = tally.get(status, 0) + 1
        if args.batch and i < len(targets) - 1:
            time.sleep(0.2)          # be polite to Crossref

    summary = "  ".join(f"{k}={v}" for k, v in sorted(tally.items()))
    print(f"enrich: {len(targets)} file(s)  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
