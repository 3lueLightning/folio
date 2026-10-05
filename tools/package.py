#!/usr/bin/env python3
"""Build dist/folio.plugin (a zip) from this repository and refuse to ship names that must not appear.

    python tools/package.py                 # writes dist/folio.plugin and dist/folio-source.zip
    python tools/package.py --terms my-terms.txt

The plugin leaves out examples/ (large demo media), tools/, CLAUDE.md, dist/ and caches.
Forbidden terms are not stored in the repository: pass a file with one term per line
(--terms) or set FOLIO_PACKAGE_TERMS to its path. Without terms only old-name leftovers are checked.
"""
import argparse, os, re, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".folio-cache", ".git", "dist"}
PLUGIN_SKIP = SKIP_DIRS | {"examples", "tools"}   # top-level examples/ and tools/ only
PLUGIN_SKIP_FILES = {"CLAUDE.md", "CLAUDE.local.md"}
TEXT = {".md", ".py", ".html", ".json", ".txt", ".css", ".svg", ".js", ""}


def files(root: Path, skip_top: set[str]):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or any(part in SKIP_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        if rel.parts[0] in skip_top and len(rel.parts) > 1:
            continue
        if skip_top is PLUGIN_SKIP and rel.as_posix() in PLUGIN_SKIP_FILES:
            continue
        yield p, rel


def scan(terms: list[str]) -> list[str]:
    hits = []
    pats = [re.compile((r"\b%s\b" if len(t.strip()) <= 3 else "%s") % re.escape(t.strip()), re.I)
            for t in terms if t.strip() and not t.startswith("#")]
    for p, rel in files(ROOT, set()):
        low = str(rel).lower()
        data = p.read_bytes()
        text = data.decode("utf-8", "ignore") if p.suffix.lower() in TEXT else ""
        for pat in pats:
            if pat.search(low) or (text and pat.search(text)):
                hits.append(f"{rel}: {pat.pattern}")
    return hits


def write_zip(target: Path, skip_top: set[str]):
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in files(ROOT, skip_top):
            z.write(p, rel.as_posix())
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terms", help="file with one forbidden term per line")
    a = ap.parse_args()
    terms = ["rich" + "doc", "next" + "slide"]
    tf = a.terms or os.environ.get("FOLIO_PACKAGE_TERMS")
    if tf:
        terms += Path(tf).read_text(encoding="utf-8").splitlines()
    hits = scan(terms)
    if hits:
        print("Refusing to package. Found:\n  " + "\n  ".join(hits), file=sys.stderr)
        return 1
    for name, skip in (("folio.plugin", PLUGIN_SKIP), ("folio-source.zip", {"dist"})):
        t = write_zip(ROOT / "dist" / name, skip)
        print(f"{t.relative_to(ROOT)}  {t.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
