"""Parse folio Markdown source into the content model, and back again.

The content model is the single source of truth that both the build script and
the in-browser editor operate on. Keeping the model and the Markdown in sync in
both directions means an edit made in the browser can be written back to the
source file without losing anything.

Model shape:

    {
      "meta":   {"title", "format", "theme", "accent", "docId"},
      "blocks": [
        {"id": "s1", "type": "section", "layout": "default",
         "title": "...", "notes": "...",
         "content": [
            {"id": "s1c1", "type": "p",       "text": "..."},
            {"id": "s1c2", "type": "bullets", "items": ["...", "..."]},
            {"id": "s1c3", "type": "media",   "asset": "a1", "caption": "..."},
            {"id": "s1c4", "type": "quote",   "text": "...", "cite": "..."},
            {"id": "s1c5", "type": "code",    "text": "...", "lang": "python"},
            {"id": "s1c6", "type": "table",   "head": [...], "rows": [[...]]},
            {"id": "s1c7", "type": "heading", "text": "...", "level": 2}
         ]}
      ],
      "assets": {"a1": {"src": "media/x.png", "kind": "image", ...}}
    }

Every editable string sits at a stable dotted path such as ``s1.c2.items.0``,
which is what the browser editor binds to.
"""

from __future__ import annotations

import re
from typing import Any

MEDIA_EXT = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".bmp"},
    "video": {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac"},
    "widget": {".html", ".htm"},
}

VALID_FORMATS = {"slides", "page"}
VALID_THEMES = {"light", "dark"}
VALID_LAYOUTS = {"default", "title", "split", "split-left", "full", "center", "cards", "stats"}
# Brands can define their own layouts, so any lower-case slug is accepted.
_LAYOUT_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def media_kind(path: str) -> str:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for kind, exts in MEDIA_EXT.items():
        if ext in exts:
            return kind
    return "file"


# --------------------------------------------------------------------------
# Markdown -> model
# --------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ATTRS = re.compile(r"\{([^{}]*)\}\s*$")
_MEDIA = re.compile(r"^!\[(.*?)\]\(\s*(\S+?)\s*\)\s*(?:\{([^{}]*)\})?\s*$")
_PARAM = re.compile(r"([A-Za-z_][\w-]*)=(\"[^\"]*\"|'[^']*'|\S+)")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_FENCE = re.compile(r"^```\s*(\w+)?\s*([^`]*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_NOTE = re.compile(r"^(?:Note|Notes|NOTE):\s*(.*)$")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Read the leading YAML-ish block. Flat ``key: value`` pairs only."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def _parse_attrs(raw: str) -> tuple[str, dict[str, str]]:
    """Pull a trailing ``{layout=split accent=#ff0}`` off a heading."""
    match = _ATTRS.search(raw)
    if not match:
        return raw.strip(), {}
    attrs: dict[str, str] = {}
    for token in match.group(1).split():
        if "=" in token:
            key, value = token.split("=", 1)
            attrs[key.strip().lower()] = value.strip().strip("\"'")
        else:
            attrs[token.strip().lower()] = "true"
    return raw[: match.start()].strip(), attrs


def parse_param_string(text: str) -> dict[str, str]:
    """Read ``height=60 delay="80 min"`` into a dict of strings."""
    params: dict[str, str] = {}
    for key, value in _PARAM.findall(text or ""):
        params[key] = value[1:-1] if value[:1] in "\"'" and value[-1:] == value[:1] else value
    return params


def format_params(params: dict[str, str]) -> str:
    parts = []
    for key, value in params.items():
        value = str(value)
        parts.append(f'{key}="{value}"' if re.search(r"\s", value) else f"{key}={value}")
    return " ".join(parts)


def _split_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def parse_markdown(text: str) -> dict[str, Any]:
    """Turn folio Markdown into the content model."""
    meta_raw, body = _parse_frontmatter(text)

    fmt = meta_raw.get("format", "slides").lower()
    theme = meta_raw.get("theme", "").lower()
    meta = {
        "title": meta_raw.get("title", "Untitled"),
        "format": fmt if fmt in VALID_FORMATS else "slides",
        "theme": theme if theme in VALID_THEMES else "",
        "accent": meta_raw.get("accent", ""),
        "subtitle": meta_raw.get("subtitle", ""),
        "footer": meta_raw.get("footer", ""),
        "sound": meta_raw.get("sound", ""),
        "brand": meta_raw.get("brand", ""),
    }

    blocks: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    asset_by_src: dict[str, str] = {}

    section: dict[str, Any] | None = None
    counters = {"section": 0, "content": 0, "asset": 0}

    def new_section(title: str = "", layout: str = "default") -> dict[str, Any]:
        counters["section"] += 1
        counters["content"] = 0
        return {
            "id": f"s{counters['section']}",
            "type": "section",
            "layout": layout,
            "title": title,
            "notes": "",
            "content": [],
        }

    def ensure_section() -> dict[str, Any]:
        nonlocal section
        if section is None:
            section = new_section()
        return section

    def push(item: dict[str, Any]) -> None:
        host = ensure_section()
        counters["content"] += 1
        item["id"] = f"{host['id']}c{counters['content']}"
        host["content"].append(item)

    def flush_section() -> None:
        nonlocal section
        if section is not None:
            blocks.append(section)
            section = None

    def register_asset(src: str, caption: str) -> str:
        if src in asset_by_src:
            return asset_by_src[src]
        counters["asset"] += 1
        asset_id = f"a{counters['asset']}"
        assets[asset_id] = {"src": src, "kind": media_kind(src)}
        asset_by_src[src] = asset_id
        return asset_id

    lines = body.split("\n")
    index = 0
    paragraph: list[str] = []
    bullets: list[str] = []
    bullets_ordered = False
    quote: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            push({"type": "p", "text": " ".join(paragraph).strip()})
            paragraph = []

    def flush_bullets() -> None:
        nonlocal bullets, bullets_ordered
        if bullets:
            push({"type": "bullets", "ordered": bullets_ordered, "items": bullets})
            bullets = []
            bullets_ordered = False

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            text = " ".join(quote).strip()
            cite = ""
            cite_match = re.search(r"\s+[-–]{1,2}\s*(.+)$", text)
            if cite_match:
                cite = cite_match.group(1).strip()
                text = text[: cite_match.start()].strip()
            push({"type": "quote", "text": text, "cite": cite})
            quote = []

    def flush_inline() -> None:
        flush_paragraph()
        flush_bullets()
        flush_quote()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # Fenced code, taken verbatim.
        fence = _FENCE.match(stripped)
        if fence:
            flush_inline()
            lang = fence.group(1) or ""
            index += 1
            code: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            if lang == "widget":
                item = {"type": "widget", "html": "\n".join(code)}
                params = parse_param_string(fence.group(2) or "")
                if params:
                    item["params"] = params
                push(item)
            else:
                push({"type": "code", "lang": lang, "text": "\n".join(code)})
            continue

        # Section break.
        if stripped in {"---", "***", "___"}:
            flush_inline()
            flush_section()
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_bullets()
            flush_quote()
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_inline()
            level = len(heading.group(1))
            title, attrs = _parse_attrs(heading.group(2))
            if level == 1:
                flush_section()
                layout = attrs.get("layout", "default")
                section = new_section(
                    title, layout if (layout in VALID_LAYOUTS or _LAYOUT_SLUG.match(layout or "")) else "default"
                )
                for key, value in attrs.items():
                    if key != "layout":
                        section[key] = value
            else:
                push({"type": "heading", "level": level, "text": title})
            index += 1
            continue

        media = _MEDIA.match(stripped)
        if media:
            flush_inline()
            caption, src = media.group(1), media.group(2)
            asset_id = register_asset(src, caption)
            item = {"type": "media", "asset": asset_id, "caption": caption}
            params = parse_param_string(media.group(3) or "")
            if params:
                item["params"] = params
            push(item)
            index += 1
            continue

        note = _NOTE.match(stripped)
        if note:
            flush_inline()
            host = ensure_section()
            existing = host.get("notes", "")
            host["notes"] = (existing + " " + note.group(1)).strip()
            index += 1
            continue

        quote_match = _QUOTE.match(stripped)
        if quote_match:
            flush_paragraph()
            flush_bullets()
            quote.append(quote_match.group(1))
            index += 1
            continue

        bullet = _BULLET.match(line)
        number = _NUMBER.match(line)
        if bullet or number:
            flush_paragraph()
            flush_quote()
            if number and not bullets:
                bullets_ordered = True
            bullets.append((bullet or number).group(1).strip())
            index += 1
            continue

        # Table: a header row followed by a separator row.
        if "|" in stripped and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
            flush_inline()
            head = _split_table_row(stripped)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            push({"type": "table", "head": head, "rows": rows})
            continue

        flush_bullets()
        flush_quote()
        paragraph.append(stripped)
        index += 1

    flush_inline()
    flush_section()

    if not blocks:
        blocks.append(new_section(meta["title"]))

    if meta["sound"]:
        assets["bgsound"] = {"src": meta["sound"], "kind": "audio"}

    return {"meta": meta, "blocks": blocks, "assets": assets}


# --------------------------------------------------------------------------
# model -> Markdown
# --------------------------------------------------------------------------

def model_to_markdown(model: dict[str, Any]) -> str:
    """Regenerate source Markdown, so browser edits can be written back."""
    meta = model.get("meta", {})
    out: list[str] = ["---"]
    for key in ("title", "subtitle", "format", "theme", "accent", "footer", "sound", "brand"):
        value = meta.get(key, "")
        if value:
            out.append(f"{key}: {value}")
    out.append("---")
    out.append("")

    assets = model.get("assets", {})
    sections = model.get("blocks", [])

    for position, section in enumerate(sections):
        if position:
            out.extend(["---", ""])

        title = section.get("title", "")
        layout = section.get("layout", "default")
        if title or layout != "default":
            suffix = f" {{layout={layout}}}" if layout != "default" else ""
            out.append(f"# {title}{suffix}")
            out.append("")

        for item in section.get("content", []):
            kind = item.get("type")
            if kind == "p":
                out.extend([item.get("text", ""), ""])
            elif kind == "heading":
                level = max(2, min(6, int(item.get("level", 2))))
                out.extend([f"{'#' * level} {item.get('text', '')}", ""])
            elif kind == "bullets":
                ordered = item.get("ordered")
                for number, entry in enumerate(item.get("items", []), start=1):
                    out.append(f"{number}. {entry}" if ordered else f"- {entry}")
                out.append("")
            elif kind == "media":
                src = assets.get(item.get("asset", ""), {}).get("src", "")
                tail = f" {{{format_params(item['params'])}}}" if item.get("params") else ""
                out.extend([f"![{item.get('caption', '')}]({src}){tail}", ""])
            elif kind == "widget":
                head = "```widget"
                if item.get("params"):
                    head += " " + format_params(item["params"])
                out.extend([head, item.get("html", ""), "```", ""])
            elif kind == "quote":
                cite = item.get("cite", "")
                tail = f" - {cite}" if cite else ""
                out.extend([f"> {item.get('text', '')}{tail}", ""])
            elif kind == "code":
                out.append(f"```{item.get('lang', '')}")
                out.append(item.get("text", ""))
                out.extend(["```", ""])
            elif kind == "table":
                head = item.get("head", [])
                out.append("| " + " | ".join(head) + " |")
                out.append("|" + "|".join([" --- "] * len(head)) + "|")
                for row in item.get("rows", []):
                    out.append("| " + " | ".join(row) + " |")
                out.append("")

        notes = section.get("notes", "")
        if notes:
            out.extend([f"Note: {notes}", ""])

    return "\n".join(out).rstrip() + "\n"


def apply_edits(model: dict[str, Any], edits: dict[str, Any]) -> int:
    """Apply ``{"s1.c2.text": "new"}`` style edits to the model in place.

    Returns the number of values actually changed.
    """
    index: dict[str, dict[str, Any]] = {}
    for section in model.get("blocks", []):
        index[section["id"]] = section
        for item in section.get("content", []):
            index[item["id"]] = item

    changed = 0
    for path, value in (edits.get("edits") or edits).items():
        parts = path.split(".")
        if not parts:
            continue
        if parts[0] == "meta" and len(parts) == 2:
            if model["meta"].get(parts[1]) != value:
                model["meta"][parts[1]] = value
                changed += 1
            continue
        target = index.get(parts[0])
        if target is None:
            continue
        cursor: Any = target
        for step in parts[1:-1]:
            if isinstance(cursor, list):
                cursor = cursor[int(step)] if step.isdigit() else None
            elif isinstance(cursor, dict):
                cursor = cursor.get(step)
            if cursor is None:
                break
        if cursor is None:
            continue
        leaf = parts[-1]
        if isinstance(cursor, list) and leaf.isdigit():
            position = int(leaf)
            if 0 <= position < len(cursor) and cursor[position] != value:
                cursor[position] = value
                changed += 1
        elif isinstance(cursor, dict) and cursor.get(leaf) != value:
            cursor[leaf] = value
            changed += 1
    return changed
