#!/usr/bin/env python3
"""Build a self-contained HTML document from a folio Markdown source.

    python build_folio.py deck.md
    python build_folio.py deck.md -o out/deck.html
    python build_folio.py deck.md --apply deck-changes.json --write-source

Everything the document needs (styles, script, images, video, audio) ends up
inside one .html file that opens by double-clicking, with no server and no
folder of assets beside it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import folio_brand as brand_mod  # noqa: E402
import folio_media as media_mod  # noqa: E402
from folio_model import apply_edits, model_to_markdown, parse_markdown  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template.html"

EMAIL_LIMIT = 25 * 1024 * 1024
BROWSER_LIMIT = 50 * 1024 * 1024


def make_icon(model: dict, assets: dict) -> str:
    """A small tab/file icon: the first picture in the document, else the accent colour and an initial."""
    import base64
    import io

    accent = model["meta"].get("accent", "#2f6df6")
    initial = (model["meta"].get("title", "R").strip() or "R")[0].upper()

    first = None
    for section in model["blocks"]:
        for item in section.get("content", []):
            asset = assets.get(item.get("asset", "")) if item.get("type") == "media" else None
            if asset and asset.get("kind") == "image" and asset.get("data") and "svg" not in asset.get("mime", ""):
                first = asset
                break
        if first:
            break

    try:
        from PIL import Image, ImageDraw, ImageFont

        if first:
            img = Image.open(io.BytesIO(base64.b64decode(first["data"]))).convert("RGB")
            side = min(img.size)
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((96, 96), Image.LANCZOS)
        else:
            img = Image.new("RGB", (96, 96), accent)
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default(size=64)
            except TypeError:
                font = ImageFont.load_default()
            draw.text((48, 50), initial, fill="white", font=font, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - an icon must never fail a build
        svg = (
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='{accent}'/>"
            f"<text x='32' y='44' font-size='36' font-family='sans-serif' font-weight='700' text-anchor='middle' fill='white'>{initial}</text></svg>"
        )
        return "data:image/svg+xml," + svg.replace("#", "%23").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")


def make_cover(model: dict, assets: dict, brand: dict | None = None) -> tuple[str, str]:
    """Static first-slide markup shown only where scripts do not run.

    Pure HTML and CSS on purpose: file thumbnailers (Finder, Explorer) and mail
    previews often skip embedded images but do draw plain markup and gradients.
    """
    import html as H
    import re as _re

    section = model["blocks"][0] if model["blocks"] else {}
    title = section.get("title") or model["meta"].get("title", "")
    text = next((i.get("text", "") for i in section.get("content", []) if i.get("type") == "p"),
                model["meta"].get("subtitle", ""))
    text = _re.sub(r"[*_`]", "", text)

    accent = str(model["meta"].get("accent", "#2f6df6")).lstrip("#")
    if len(accent) == 3:
        accent = "".join(c * 2 for c in accent)
    try:
        r, g, b = (int(accent[k:k + 2], 16) for k in (0, 2, 4))
    except ValueError:
        r, g, b = 47, 109, 246
    dark = model["meta"].get("theme") == "dark"
    base, fg = ("#0d0f14", "#ffffff") if dark else ("#f4f6f9", "#14171c")
    colors = (brand or {}).get("colors") or {}
    if colors.get("title_bg"):
        base, fg = colors["title_bg"], colors.get("title_fg", "#ffffff")
        dark = True
    strong, soft = (0.55, 0.3) if dark else (0.28, 0.14)
    style = (
        f' style="background:radial-gradient(120% 90% at 85% 0%,rgba({r},{g},{b},{strong}),rgba({r},{g},{b},0) 60%),'
        f'radial-gradient(90% 80% at 0% 100%,rgba({r},{g},{b},{soft}),rgba({r},{g},{b},0) 65%),{base};color:{fg}"'
    )
    parts = [f"<h1>{H.escape(title)}</h1>"]
    if text:
        parts.append(f"<p>{H.escape(text)}</p>")
    return "".join(parts), style


def embed_json(value: object) -> str:
    """JSON safe to drop inside a <script> block."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


class ForbiddenTermsError(Exception):
    """Raised when a term the author said must not appear is in the document."""

    def __init__(self, hits: list[dict]) -> None:
        super().__init__(f"{len(hits)} forbidden term hit(s)")
        self.hits = hits


_NOT_CONTENT = {"id", "type", "layout", "asset", "lang", "ordered", "level"}


def _walk(value: object, label: str):
    if isinstance(value, str):
        yield label, value
    elif isinstance(value, dict):
        for key, inner in value.items():
            if key not in _NOT_CONTENT:
                yield from _walk(inner, label)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk(inner, label)


def collect_text(model: dict, assets: dict):
    """Every string a reader could ever see, tagged with where it lives."""
    for key, value in model["meta"].items():
        if isinstance(value, str) and key != "docId":
            yield f"header field '{key}'", value
    for number, section in enumerate(model["blocks"], start=1):
        yield from _walk(section, f"section {number}")
    for asset in assets.values():
        label = f"media file {asset.get('src', '?')}"
        yield label, asset.get("src", "")
        if asset.get("kind") == "widget":
            yield label, asset.get("scan", asset.get("html", ""))


def find_forbidden(
    terms: list[str], exact_terms: list[str], chunks
) -> list[dict]:
    """Whole-word matches of each term, with a little context for review."""
    patterns = [
        (term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE))
        for term in terms
    ] + [
        (term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)"))
        for term in exact_terms
    ]
    hits: list[dict] = []
    for label, text in chunks:
        for term, pattern in patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                context = text[max(0, start - 35): end + 35].replace("\n", " ")
                hits.append({"term": term, "where": label, "context": context.strip()})
    return hits


_EXTERNAL_URL = re.compile(r"https?://[^\s\"'<>)\\]+")


def lint_widgets(model: dict, assets: dict) -> list[str]:
    """Warn about anything a widget reaches for that the sandbox will refuse."""
    sources: list[tuple[str, str]] = []
    for number, section in enumerate(model["blocks"], start=1):
        for item in section.get("content", []):
            if item.get("type") == "widget":
                sources.append((f"inline widget in section {number}", item.get("html", "")))
    for asset in assets.values():
        if asset.get("kind") == "widget":
            sources.append((f"widget {asset.get('src')}", asset.get("html", "")))

    warnings = []
    for label, text in sources:
        urls = {
            url for url in _EXTERNAL_URL.findall(text)
            if "www.w3.org" not in url
        }
        for url in sorted(urls)[:3]:
            warnings.append(
                f"{label} mentions {url}. Widgets run with all network access "
                "blocked, so inline that resource instead."
            )
    return warnings


def build(
    source: Path,
    output: Path | None = None,
    apply_file: Path | None = None,
    write_source: bool = False,
    settings: dict | None = None,
    template: Path | None = None,
    quiet: bool = False,
    forbid: list[str] | None = None,
    forbid_exact: list[str] | None = None,
    brand: str | None = None,
    home: str | None = None,
) -> tuple[Path, list[str]]:
    source = source.resolve()
    text = source.read_text(encoding="utf-8")
    model = parse_markdown(text)

    def say(message: str = "") -> None:
        if not quiet:
            print(message)

    if apply_file is not None:
        edits = json.loads(Path(apply_file).read_text(encoding="utf-8"))
        changed = apply_edits(model, edits)
        say(f"Applied {changed} change(s) from {Path(apply_file).name}")
        if write_source:
            source.write_text(model_to_markdown(model), encoding="utf-8")
            say(f"Source updated: {source.name}")

    brand_info = None
    brand_ref = brand or model["meta"].get("brand", "")
    if brand_ref:
        if not home and not os.environ.get(brand_mod.HOME_ENV):
            for folder in source.parents:
                if (folder / "brands").is_dir():
                    home = str(folder)
                    break
        brand_info = brand_mod.load_brand(
            brand_ref, home, inline_assets=media_mod.inline_widget_assets, settings=settings
        )
        meta = model["meta"]
        meta["brand"] = brand_ref
        if not meta["theme"]:
            meta["theme"] = brand_info["mode"] if brand_info["mode"] in ("light", "dark") else "light"
        if not meta["footer"]:
            meta["footer"] = brand_info["footer"]
        if brand_info["logo"]:
            meta["logo"] = brand_info["logo"]["uri"]
            meta["logoWhere"] = brand_info["logo"]["where"]
            meta["logoHeight"] = brand_info["logo"]["height"]
            meta["logoText"] = brand_info["logo"].get("text", "")
        forbid = list(forbid or []) + brand_info["forbid"]
        forbid_exact = list(forbid_exact or []) + brand_info["forbid_exact"]
        say(f"Brand: {brand_info['name']} ({brand_info['dir']})")
        known = {"default", "title", "split", "split-left", "full", "center", "cards", "stats"}
        for section in model["blocks"]:
            layout = section.get("layout", "default")
            if layout not in known and f"layout-{layout}" not in brand_info["css"]:
                brand_info["warnings"].append(
                    f"layout '{layout}' is not defined in brand '{brand_info['name']}'; it will look like the default."
                )
    if not model["meta"]["theme"]:
        model["meta"]["theme"] = "light"

    model["meta"]["docId"] = hashlib.sha1(
        str(source).encode("utf-8")
    ).hexdigest()[:12]

    say(f"Media ({len(model['assets'])} file(s)):" if model["assets"] else "Media: none")
    assets, warnings = media_mod.process(
        model["assets"], source.parent, settings=settings, verbose=not quiet
    )

    warnings.extend(lint_widgets(model, assets))
    if brand_info:
        warnings.extend(brand_info["warnings"])

    if forbid or forbid_exact:
        hits = find_forbidden(
            forbid or [], forbid_exact or [], collect_text(model, assets)
        )
        if hits:
            raise ForbiddenTermsError(hits)
        say("Forbidden-term check passed (text, notes, widgets, file names).")

    for asset in assets.values():
        asset.pop("scan", None)

    payload = {"meta": model["meta"], "blocks": model["blocks"]}
    view = {
        "blocks": model["blocks"],
        "meta": {**model["meta"], "accent": model["meta"].get("accent")
                 or ((brand_info or {}).get("colors") or {}).get("accent") or "#2f6df6"},
    }
    cover_html, cover_style = make_cover(view, assets, brand_info)
    values = {
        "TITLE": model["meta"]["title"].replace("<", "&lt;"),
        "BRANDCSS": (brand_info or {}).get("css", "").replace("</style", "<\\/style"),
        "ICON": make_icon(view, assets),
        "COVER": cover_html,
        "COVERSTYLE": cover_style,
        "MODEL": embed_json(payload),
        "ASSETS": embed_json(assets),
    }
    # One pass over the template, so text inside the model or a widget that
    # happens to look like a placeholder is never substituted a second time.
    html = re.sub(
        r"__(TITLE|MODEL|ASSETS|ICON|COVERSTYLE|COVER|BRANDCSS)__",
        lambda m: values[m.group(1)],
        (template or TEMPLATE).read_text(encoding="utf-8"),
    )

    output = (output or source.with_suffix(".html")).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    size = output.stat().st_size
    media_bytes = sum(a.get("bytes", 0) for a in assets.values())
    encoded = sum(len(a.get("data", "")) for a in assets.values())
    say()
    say(f"Built {output}")
    say(
        f"  {len(model['blocks'])} section(s), "
        f"{size / 1e6:.2f} MB total "
        f"({media_bytes / 1e6:.2f} MB media before encoding, "
        f"{max(size - encoded, 0) / 1e3:.0f} kB document)"
    )

    if size > BROWSER_LIMIT:
        warnings.append(
            f"{size / 1e6:.0f} MB is above the 50 MB point where browsers get slow "
            "to open the file. Shorten video clips or lower --video-width."
        )
    elif size > EMAIL_LIMIT:
        warnings.append(
            f"{size / 1e6:.0f} MB is above the 25 MB attachment limit most mail "
            "servers enforce. Share it through Teams, SharePoint or OneDrive."
        )

    if warnings and not quiet:
        say()
        for warning in warnings:
            say(f"  ! {warning}")
    if not warnings and not quiet:
        say("  Fits an email attachment and opens quickly.")

    return output, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a single-file HTML document from Markdown."
    )
    parser.add_argument("source", type=Path, help="the .md source file")
    parser.add_argument("-o", "--output", type=Path, help="output .html path")
    parser.add_argument(
        "--apply", type=Path, metavar="EDITS.JSON",
        help="fold in a changes file exported from the browser",
    )
    parser.add_argument(
        "--write-source", action="store_true",
        help="with --apply, also write the changes back into the .md source",
    )
    parser.add_argument("--image-width", type=int, default=1920)
    parser.add_argument("--image-quality", type=int, default=80)
    parser.add_argument("--video-width", type=int, default=1280)
    parser.add_argument(
        "--video-crf", type=int, default=30,
        help="video quality, 18 is near-lossless and 34 is small (default 30)",
    )
    parser.add_argument("--audio-bitrate", default="128k")
    parser.add_argument(
        "--forbid", default="", metavar="TERMS",
        help="comma-separated names that must not appear anywhere (slides, notes, "
             "widgets, header, file names). Whole words, ignoring case. If one is "
             "found the build stops and writes nothing. Pictures are not scanned.",
    )
    parser.add_argument(
        "--forbid-exact", default="", metavar="TERMS",
        help="like --forbid but case-sensitive, for short acronyms that are also "
             "ordinary words in lower case",
    )
    parser.add_argument("--brand", default=None, help="brand name or folder (overrides the header's brand:)")
    parser.add_argument("--home", default=None, help="folder that holds brands/ (default: $FOLIO_HOME, a parent folder, or ~/folio-templates)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source not found: {args.source}", file=sys.stderr)
        return 1

    def split(raw: str) -> list[str]:
        return [part.strip() for part in raw.split(",") if part.strip()]

    try:
        build(
            args.source,
            output=args.output,
            apply_file=args.apply,
            write_source=args.write_source,
            settings={
                "image_max_width": args.image_width,
                "image_quality": args.image_quality,
                "video_max_width": args.video_width,
                "video_crf": args.video_crf,
                "audio_bitrate": args.audio_bitrate,
            },
            quiet=args.quiet,
            forbid=split(args.forbid),
            forbid_exact=split(args.forbid_exact),
            brand=args.brand,
            home=args.home,
        )
    except FileNotFoundError as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    except ForbiddenTermsError as error:
        print("\nBuild stopped. Forbidden terms found, no file was written:\n", file=sys.stderr)
        for hit in error.hits[:25]:
            print(f"  '{hit['term']}' in {hit['where']}: ...{hit['context']}...", file=sys.stderr)
        if len(error.hits) > 25:
            print(f"  and {len(error.hits) - 25} more", file=sys.stderr)
        print(
            "\nRemove or reword these. If a hit is an ordinary word (for example "
            "'abc' when the term is an acronym), use --forbid-exact instead.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
