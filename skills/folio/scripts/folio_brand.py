#!/usr/bin/env python3
"""Brand folders for folio: create, import from PowerPoint, list, check.

A brand lives in the person's OWN folder (or Git repo), never inside the plugin:

    <home>/
      brands/<name>/
        brand.json        colours, fonts, logo, footer, defaults
        guidelines.md     look and feel and content rules (read by the agent)
        assets/           fonts, logo, images
        layouts/*.css     optional extra layouts, used as {layout=name}
        reference/        screenshots of the original slides
        forbid.txt        names that must never appear in decks using this brand
      decks/<name>/       finished decks kept as starting points
      widgets/            reusable interactive pieces

Where <home> is found: --home, then $FOLIO_HOME, then the nearest folder above
the current one that contains `brands/`, then ~/folio-templates.

    python folio_brand.py init acme
    python folio_brand.py import-pptx template.pptx --name acme --fetch-fonts
    python folio_brand.py list
    python folio_brand.py check acme
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HOME_ENV = "FOLIO_HOME"

# Fonts every computer already has. They are never embedded, only named.
SYSTEM_FONTS = {
    "arial", "helvetica", "helvetica neue", "calibri", "cambria", "segoe ui", "verdana", "tahoma",
    "times new roman", "georgia", "trebuchet ms", "courier new", "consolas", "san francisco",
    "sf pro", "system-ui", "aptos", "candara", "garamond", "palatino", "arial narrow",
}
FALLBACK_SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
FALLBACK_SERIF = '"Iowan Old Style", Palatino, Georgia, serif'

MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".woff2": "font/woff2", ".woff": "font/woff", ".gif": "image/gif"}


# ---------------------------------------------------------------- locating

def find_home(explicit: str | Path | None = None, create: bool = False) -> Path:
    if explicit:
        home = Path(explicit).expanduser()
    elif os.environ.get(HOME_ENV):
        home = Path(os.environ[HOME_ENV]).expanduser()
    else:
        home = None
        here = Path.cwd().resolve()
        for folder in [here, *here.parents]:
            if (folder / "brands").is_dir():
                home = folder
                break
        if home is None:
            pointer = Path.home() / ".folio" / "home"
            if pointer.exists() and (Path(pointer.read_text(encoding="utf-8").strip()) / "brands").is_dir():
                home = Path(pointer.read_text(encoding="utf-8").strip())
        if home is None:
            home = Path.home() / "folio-templates"
    if create:
        for sub in ("brands", "decks", "widgets"):
            (home / sub).mkdir(parents=True, exist_ok=True)
    return home.resolve()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "brand"


def resolve_brand(ref: str, home: Path | None) -> Path:
    """A brand reference is a folder path or a name under <home>/brands/."""
    direct = Path(ref).expanduser()
    if direct.is_dir() and (direct / "brand.json").exists():
        return direct.resolve()
    folder = find_home(home) / "brands" / slugify(ref)
    if (folder / "brand.json").exists():
        return folder
    raise FileNotFoundError(
        f"brand '{ref}' not found. Looked in {folder}. Create it with: "
        f"python folio_brand.py init {slugify(ref)}"
    )


# ---------------------------------------------------------------- colour helpers

def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in rgb)


def mix(a: str, b: str, amount: float) -> str:
    """amount of b mixed into a."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(ra[i] + (rb[i] - ra[i]) * amount for i in range(3)))


def luminance(value: str) -> float:
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_rgb(value)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---------------------------------------------------------------- loading for the build

def _read_forbid(path: Path) -> tuple[list[str], list[str]]:
    loose, exact = [], []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("exact:"):
                exact.append(line[6:].strip())
            else:
                loose.append(line)
    return loose, exact


def _font_faces(brand_dir: Path, cfg: dict, warnings: list[str]) -> tuple[str, dict[str, str]]:
    css, stacks = [], {}
    for role in ("heading", "body", "mono"):
        font = (cfg.get("fonts") or {}).get(role)
        if not font or not font.get("family"):
            continue
        family = font["family"]
        fallback = font.get("fallback") or (FALLBACK_SERIF if role == "heading" and font.get("serif") else FALLBACK_SANS)
        stacks[role] = f'"{family}", {fallback}'
        for weight, rel in (font.get("files") or {}).items():
            path = brand_dir / rel
            if not path.exists():
                warnings.append(f"brand font file missing: {rel} (the page falls back to {fallback.split(',')[0]})")
                continue
            mime = MIME.get(path.suffix.lower(), "font/woff2")
            fmt = "woff2" if path.suffix.lower() == ".woff2" else "woff"
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            css.append(
                f'@font-face{{font-family:"{family}";font-weight:{weight};font-style:normal;'
                f'font-display:swap;src:url(data:{mime};base64,{data}) format("{fmt}")}}'
            )
    return "".join(css), stacks


def load_brand(ref: str, home: str | Path | None, inline_assets=None, settings: dict | None = None) -> dict[str, Any]:
    """Everything the build needs from a brand: CSS, logo, footer, forbidden names."""
    brand_dir = resolve_brand(ref, Path(home) if home else None)
    cfg = json.loads((brand_dir / "brand.json").read_text(encoding="utf-8"))
    warnings: list[str] = []

    faces, stacks = _font_faces(brand_dir, cfg, warnings)
    colors = cfg.get("colors") or {}
    dark = colors.get("dark") or {}

    def block(selector: str, values: dict) -> str:
        names = {"accent": "--accent", "bg": "--bg", "fg": "--fg", "muted": "--muted", "line": "--line", "panel": "--panel"}
        decl = [f"{names[k]}:{values[k]}" for k in names if values.get(k)]
        return f"{selector}{{{';'.join(decl)}}}" if decl else ""

    light_vars = {k: colors.get(k) for k in ("accent", "bg", "fg", "muted", "line", "panel")}
    css = [faces, block(":root", light_vars), block(':root[data-theme="dark"]', {"accent": dark.get("accent", colors.get("accent")), **{k: dark.get(k) for k in ("bg", "fg", "muted", "line", "panel")}})]

    root_extra = []
    if stacks.get("body"):
        root_extra.append(f"--sans:{stacks['body']}")
    if stacks.get("heading"):
        root_extra.append(f"--head:{stacks['heading']}")
    if stacks.get("mono"):
        root_extra.append(f"--mono:{stacks['mono']}")
    for index, color in enumerate(cfg.get("palette") or [], start=1):
        root_extra.append(f"--c{index}:{color}")
    if root_extra:
        css.append(":root{" + ";".join(root_extra) + "}")

    if colors.get("title_bg"):
        title_fg = colors.get("title_fg", "#ffffff")
        css.append(
            f".slide.layout-title{{background:{colors['title_bg']};color:{title_fg}}}"
            f".slide.layout-title h1{{background:none;-webkit-text-fill-color:{title_fg};color:{title_fg}}}"
            f".slide.layout-title p{{color:{title_fg};opacity:.9}}"
        )

    for name in cfg.get("layouts") or sorted(p.stem for p in (brand_dir / "layouts").glob("*.css")):
        path = brand_dir / "layouts" / f"{name}.css"
        if not path.exists():
            warnings.append(f"brand layout file missing: layouts/{name}.css")
            continue
        text = path.read_text(encoding="utf-8")
        if inline_assets:
            (brand_dir / ".folio-cache").mkdir(exist_ok=True)
            text = inline_assets(text, brand_dir, settings or {}, brand_dir / ".folio-cache", warnings)
        css.append(text)

    logo = None
    logo_cfg = cfg.get("logo") or {}
    if logo_cfg.get("file"):
        path = brand_dir / logo_cfg["file"]
        if path.exists():
            logo = {
                "uri": f"data:{MIME.get(path.suffix.lower(), 'image/png')};base64," + base64.b64encode(path.read_bytes()).decode("ascii"),
                "where": logo_cfg.get("where", "top-right"),
                "height": logo_cfg.get("height", "5.5vmin"),
                "text": logo_cfg.get("text", ""),
            }
        else:
            warnings.append(f"brand logo missing: {logo_cfg['file']}")

    loose, exact = _read_forbid(brand_dir / "forbid.txt")
    return {
        "dir": brand_dir,
        "name": cfg.get("name", brand_dir.name),
        "mode": cfg.get("mode", ""),
        "css": "\n".join(part for part in css if part),
        "logo": logo,
        "footer": cfg.get("footer", ""),
        "colors": colors,
        "forbid": loose,
        "forbid_exact": exact,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- init

DEFAULT_CONFIG = {
    "name": "",
    "description": "One line: who this brand is for and when to use it.",
    "mode": "light",
    "colors": {
        "accent": "#2f6df6", "bg": "#ffffff", "fg": "#14171c", "muted": "#5d6570", "line": "#e3e6eb", "panel": "#f6f7f9",
        "title_bg": "", "title_fg": "#ffffff",
        "dark": {"accent": "#5b8cff", "bg": "#0d0f14", "fg": "#e8eaed", "muted": "#9aa1ab", "line": "#2a2e35", "panel": "#1c1f25"},
    },
    "palette": [],
    "fonts": {
        "heading": {"family": "", "files": {}, "fallback": FALLBACK_SANS},
        "body": {"family": "", "files": {}, "fallback": FALLBACK_SANS},
    },
    "logo": {"file": "", "where": "top-right", "height": "5.5vmin"},
    "footer": "",
    "layouts": [],
}

GUIDELINES_SKELETON = """# {name}: look and feel

Read this before writing a deck with this brand. Keep it under about 2 kB.

## Look
- One sentence on the overall feel (for example: flat, airy, lots of white space).
- Imagery: what kind of pictures to use and what to avoid.

## Colour use
- Accent colour is for ...
- Never use ... together.

## Layouts to use
- Cover: `{{layout=title}}`
- Section dividers or agenda: `{{layout=cards}}`
- Key numbers: `{{layout=stats}}`
- Picture and text: `{{layout=split}}`
- Everything else: the default

## Writing rules
- Tone of voice.
- Maximum bullets per slide.
- Words or names that must never appear (also list them in forbid.txt).

## Reference
- `reference/` holds screenshots of the original slides. Look at them only when
  building a new layout, not for every deck.
"""

DESCRIPTION_SKELETON = """summary: One line on the look and when to use it. This line is shown by the list command.

# {name}

## Look and feel
- Two or three lines: overall mood, colours, type, imagery.

## Good for
- The kinds of presentation this brand suits (audience and purpose).

## Not for
- What it handles badly.

## Layouts and structures
- Layouts it defines or restyles, and what each is for.

## Widgets
- Which interactive pieces work well here, and any limits (height, no title).

## Typical outlines
- Name of outline: slide, slide, slide.
"""


def _summary(path: Path, fallback: str = "") -> str:
    """The 'summary:' line of a description.md, else the fallback."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("summary:"):
                return line.split(":", 1)[1].strip()
    return fallback


README = """# {name}

Brand folder for folio. Use it by adding `brand: {slug}` to the header of a deck
(and set FOLIO_HOME, or pass --home, to the folder that contains `brands/`).

| File | Purpose |
| --- | --- |
| brand.json | colours, fonts, logo, footer. Edit the values, keep the keys |
| description.md | what the brand looks like, what it suits, layouts, widgets, typical outlines. Lets the agent choose a brand |
| guidelines.md | the rules for writing a deck with it. The agent reads this once a brand is chosen |
| assets/fonts | .woff2 files. Only add fonts you are licensed to embed |
| assets/ | logo and images. Refer to them in layouts with {{asset:assets/x.png}} |
| layouts/*.css | extra layouts, used as {{layout=name}}. Style `.slide.layout-name` |
| reference/ | screenshots of the original slides |
| forbid.txt | names that must never appear. One per line, `exact:` for case-sensitive |
"""


def cmd_init(args: argparse.Namespace) -> int:
    home = find_home(args.home, create=True)
    slug = slugify(args.name)
    folder = home / "brands" / slug
    if folder.exists() and any(folder.iterdir()):
        print(f"{folder} already exists and is not empty. Nothing changed.", file=sys.stderr)
        return 1
    for sub in ("assets/fonts", "layouts", "reference"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["name"] = args.name
    (folder / "brand.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (folder / "guidelines.md").write_text(GUIDELINES_SKELETON.format(name=args.name), encoding="utf-8")
    (folder / "description.md").write_text(DESCRIPTION_SKELETON.format(name=args.name), encoding="utf-8")
    (folder / "forbid.txt").write_text("# One name per line. Prefix with exact: for case-sensitive matching.\n", encoding="utf-8")
    (folder / "README.md").write_text(README.format(name=args.name, slug=slug), encoding="utf-8")
    readme = home / "README.md"
    if not readme.exists():
        readme.write_text(
            "# folio templates\n\nPersonal or team folder read by the folio skill.\n\n"
            "- `brands/` colours, fonts, logo and guidelines per brand\n"
            "- `decks/` finished decks kept as starting points\n"
            "- `widgets/` reusable interactive pieces\n",
            encoding="utf-8",
        )
    print(f"Created {folder}")
    print(f"Use it with:  brand: {slug}   (in the deck header, with {HOME_ENV}={home})")
    return 0


# ---------------------------------------------------------------- list / check

def cmd_list(args: argparse.Namespace) -> int:
    home = find_home(args.home)
    print(f"Templates folder: {home}")
    brands = sorted((home / "brands").glob("*/brand.json")) if (home / "brands").is_dir() else []
    if not brands:
        print("No brands yet. Create one with: init NAME   or   import-pptx FILE")
    for path in brands:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        colors = cfg.get("colors", {})
        summary = _summary(path.parent / "description.md", cfg.get("description", ""))
        print(f"  brand {path.parent.name:<22} {cfg.get('mode', 'light'):<5} {colors.get('accent', ''):<8} {summary}")
        if args.details and (path.parent / "description.md").exists():
            body = (path.parent / "description.md").read_text(encoding="utf-8")
            print("\n".join("      " + line for line in body.splitlines() if not line.lower().startswith("summary:")) + "\n")
    decks = sorted(p for p in (home / "decks").iterdir() if p.is_dir()) if (home / "decks").is_dir() else []
    for deck in decks:
        print(f"  deck  {deck.name:<22} {_summary(deck / 'description.md')}")
        if args.details and (deck / "description.md").exists():
            body = (deck / "description.md").read_text(encoding="utf-8")
            print("\n".join("      " + line for line in body.splitlines() if not line.lower().startswith("summary:")) + "\n")
    widgets = sorted((home / "widgets").glob("*.html")) if (home / "widgets").is_dir() else []
    for path in widgets:
        first = path.read_text(encoding="utf-8", errors="ignore")[:400]
        match = re.search(r"description:\s*(.+?)\s*(?:-->|\n)", first)
        print(f"  widget {path.name:<21} {match.group(1) if match else ''}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    folder = resolve_brand(args.name, find_home(args.home))
    cfg = json.loads((folder / "brand.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    colors = cfg.get("colors", {})
    for mode, vals in (("light", colors), ("dark", colors.get("dark", {}))):
        if vals.get("bg") and vals.get("fg") and contrast(vals["bg"], vals["fg"]) < 4.5:
            problems.append(f"{mode}: text on background contrast is {contrast(vals['bg'], vals['fg']):.1f}:1 (aim for 4.5 or more)")
        if vals.get("bg") and vals.get("accent") and contrast(vals["bg"], vals["accent"]) < 3:
            problems.append(f"{mode}: accent on background contrast is {contrast(vals['bg'], vals['accent']):.1f}:1 (aim for 3 or more)")
    if colors.get("title_bg") and contrast(colors["title_bg"], colors.get("title_fg", "#ffffff")) < 3:
        problems.append("cover: title text on cover colour is hard to read")
    for role, font in (cfg.get("fonts") or {}).items():
        if font.get("family") and not font.get("files") and font["family"].lower() not in SYSTEM_FONTS:
            problems.append(f"font '{font['family']}' ({role}) has no files: pages fall back to a system font unless the viewer has it installed")
        for weight, rel in (font.get("files") or {}).items():
            if not (folder / rel).exists():
                problems.append(f"font file missing: {rel}")
    logo = (cfg.get("logo") or {}).get("file")
    if logo and not (folder / logo).exists():
        problems.append(f"logo file missing: {logo}")
    guide = folder / "guidelines.md"
    if not guide.exists():
        problems.append("guidelines.md is missing")
    elif guide.stat().st_size > 4000:
        problems.append("guidelines.md is over 4 kB: the agent reads it every time, keep it short")
    desc = folder / "description.md"
    if not desc.exists():
        problems.append("description.md is missing: without it the agent cannot tell when to choose this brand")
    else:
        text = desc.read_text(encoding="utf-8")
        if "TODO" in text or "Two or three lines" in text or "One line on the look" in text:
            problems.append("description.md still has placeholder text")
        if len(text) > 2200:
            problems.append("description.md is over about 2 kB: it is read for every brand when choosing, keep it short")
    for problem in problems:
        print(f"  ! {problem}")
    print("OK" if not problems else f"{len(problems)} thing(s) to look at")
    return 0 if not problems else 1


# ---------------------------------------------------------------- import from PowerPoint

A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _theme(prs) -> tuple[dict[str, str], str, str]:
    from lxml import etree
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    colors: dict[str, str] = {}
    scheme = root.find(".//a:clrScheme", A_NS)
    if scheme is not None:
        for child in scheme:
            tag = etree.QName(child).localname
            srgb = child.find("a:srgbClr", A_NS)
            sysc = child.find("a:sysClr", A_NS)
            if srgb is not None:
                colors[tag] = "#" + srgb.get("val").lower()
            elif sysc is not None:
                colors[tag] = "#" + sysc.get("lastClr", "000000").lower()
    major = root.find(".//a:majorFont/a:latin", A_NS)
    minor = root.find(".//a:minorFont/a:latin", A_NS)
    return colors, (major.get("typeface") if major is not None else ""), (minor.get("typeface") if minor is not None else "")


def _is_default_office(theme: dict[str, str], major: str, minor: str) -> bool:
    """Exports from Canva and similar tools keep PowerPoint's stock theme and draw the design in the slides."""
    return theme.get("accent1", "").lower() in ("#4f81bd", "#4472c4", "#156082") or (major in ("Calibri", "Calibri Light", "Aptos Display") and minor in ("Calibri", "Aptos"))


_STYLE_WORDS = ("bold", "semibold", "extrabold", "medium", "light", "extralight", "thin", "black", "regular", "italic")


def _family_of(face: str) -> str:
    """'Montserrat Bold' -> 'Montserrat'. Weight words are dropped, the family is what Fontsource knows."""
    words = face.split()
    while len(words) > 1 and words[-1].lower() in _STYLE_WORDS:
        words.pop()
    return " ".join(words)


def _bbox_of_top(shape):
    return shape.left or 0, shape.top or 0, shape.width or 0, shape.height or 0


def _walk(shapes, top=None):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        owner = top or shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes, owner)
        else:
            yield shape, owner


def _scan_slides(prs) -> dict[str, Any]:
    """Read what the slides themselves use: text colours, fonts, recurring pictures, recurring text."""
    from collections import Counter

    slide_w, slide_h = prs.slide_width, prs.slide_height
    text_colors: Counter = Counter()
    fills: Counter = Counter()
    faces: Counter = Counter()
    sizes: dict[str, float] = {}
    size_color: dict[str, Counter] = {}
    pictures: dict[str, dict[str, Any]] = {}
    texts: dict[str, dict[str, Any]] = {}
    slide_count = len(prs.slides)

    for index, slide in enumerate(prs.slides):
        for shape, owner in _walk(slide.shapes):
            element = shape._element
            for fill in element.xpath("./p:spPr/a:solidFill/a:srgbClr/@val"):
                fills[fill.lower()] += 1
            if shape.has_text_frame and shape.text_frame.text.strip():
                x, y, w, h = _bbox_of_top(owner)
                label = " ".join(shape.text_frame.text.split())
                entry = texts.setdefault(label, {"slides": set(), "cx": 0.0, "cy": 0.0, "h": 0})
                entry["slides"].add(index)
                entry["cx"], entry["cy"], entry["h"] = (x + w / 2) / slide_w, (y + h / 2) / slide_h, h
            for run in element.xpath(".//a:r"):
                chars = len("".join(run.xpath("./a:t/text()")).strip())
                if not chars:
                    continue
                color = (run.xpath("./a:rPr/a:solidFill/a:srgbClr/@val") or [""])[0].lower()
                face = (run.xpath("./a:rPr/a:latin/@typeface") or [""])[0]
                size = float((run.xpath("./a:rPr/@sz") or ["0"])[0]) / 100
                if color:
                    text_colors[color] += chars
                if face:
                    faces[face] += chars
                    sizes[face] = max(sizes.get(face, 0), size)
                if size and color:
                    size_color.setdefault(f"{size:g}", Counter())[color] += chars
            for rid in element.xpath(".//a:blip/@r:embed"):
                try:
                    part = shape.part.related_part(rid)
                except KeyError:
                    continue
                digest = hashlib.sha1(part.blob).hexdigest()[:10]
                x, y, w, h = _bbox_of_top(owner)
                if not (w and h):
                    continue
                svg = None
                for node in element.iter():
                    if isinstance(node.tag, str) and node.tag.endswith("}svgBlip"):
                        srid = node.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                        try:
                            svg = shape.part.related_part(srid).blob
                        except KeyError:
                            pass
                entry = pictures.setdefault(digest, {"blob": part.blob, "ext": part.partname.ext, "svg": svg, "slides": set(), "area": 0.0, "cy": 0.0, "cx": 0.0, "h": 0})
                entry["slides"].add(index)
                entry["area"] = max(entry["area"], w * h / (slide_w * slide_h))
                entry["cx"], entry["cy"], entry["h"] = (x + w / 2) / slide_w, (y + h / 2) / slide_h, h / slide_h
    return {
        "text_colors": text_colors, "fills": fills, "faces": faces, "sizes": sizes, "size_color": size_color,
        "pictures": pictures, "texts": texts, "slide_count": slide_count,
    }


def _picture_shapes(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            yield shape
        elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _picture_shapes(shape.shapes)


def _slide_background(slide) -> str | None:
    try:
        fill = slide.background.fill
        if fill.type == 1:
            return "#" + str(fill.fore_color.rgb).lower()
    except Exception:  # noqa: BLE001 - theme-based fills have no plain RGB
        return None
    return None


def _fetch_font(family: str, dest: Path, weights=("400", "700")) -> dict[str, str]:
    """Download an open-licence font from the Fontsource npm package (needs Node and npm)."""
    slug = slugify(family)
    if not shutil.which("npm"):
        print(f"  ! npm not found, cannot fetch '{family}'. Put .woff2 files in assets/fonts yourself.")
        return {}
    files: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(["npm", "pack", f"@fontsource/{slug}", "--silent"], cwd=tmp, capture_output=True, text=True, timeout=120)
        tarball = next(Path(tmp).glob("*.tgz"), None)
        if result.returncode != 0 or tarball is None:
            print(f"  ! '{family}' is not on Fontsource (open-licence fonts only). Fonts needing a licence must be added by hand.")
            return {}
        import tarfile

        with tarfile.open(tarball) as tar:
            names = {Path(m.name).name: m for m in tar.getmembers()}
            for weight in weights:
                wanted = f"{slug}-latin-{weight}-normal.woff2"
                if wanted in names:
                    out = dest / wanted
                    out.write_bytes(tar.extractfile(names[wanted]).read())
                    files[weight] = f"assets/fonts/{wanted}"
    return files


def _render_screenshots(pptx: Path, out_dir: Path, limit: int) -> int:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice or not shutil.which("pdftoppm"):
        print("  ! LibreOffice or pdftoppm not found: skipping screenshots of the original slides.")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(pptx)], capture_output=True, timeout=240)
        pdf = Path(tmp) / (pptx.stem + ".pdf")
        if not pdf.exists():
            print("  ! Could not render the presentation to PDF: skipping screenshots.")
            return 0
        subprocess.run(["pdftoppm", "-r", "72", "-scale-to-x", "960", "-scale-to-y", "-1", "-png", "-l", str(limit), str(pdf), str(Path(tmp) / "s")], capture_output=True, timeout=240)
        shots = sorted(Path(tmp).glob("s-*.png"))
        for index, shot in enumerate(shots, start=1):
            shutil.copyfile(shot, out_dir / f"slide-{index:02d}.png")
    try:
        from PIL import Image

        files = sorted(out_dir.glob("slide-*.png"))
        if files:
            thumbs = []
            for f in files:
                im = Image.open(f).convert("RGB")
                im.thumbnail((480, 480))
                thumbs.append(im)
            w, h = thumbs[0].size
            cols = min(3, len(thumbs))
            rows = (len(thumbs) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * w, rows * h), "white")
            for i, im in enumerate(thumbs):
                sheet.paste(im, ((i % cols) * w, (i // cols) * h))
            sheet.save(out_dir / "overview.png", optimize=True)
    except Exception:  # noqa: BLE001 - the overview is a convenience
        pass
    return len(list(out_dir.glob("slide-*.png")))


def cmd_import(args: argparse.Namespace) -> int:
    try:
        from pptx import Presentation
    except ImportError:
        print("python-pptx is needed for import-pptx:  pip install python-pptx", file=sys.stderr)
        return 1

    source = Path(args.file).expanduser()
    if not source.exists():
        print(f"File not found: {source}", file=sys.stderr)
        return 1
    prs = Presentation(str(source))
    home = find_home(args.home, create=True)
    name = args.name or source.stem
    slug = slugify(name)
    folder = home / "brands" / slug
    if folder.exists() and any(folder.iterdir()) and not args.force:
        print(f"{folder} already exists. Use --force to overwrite or pick another --name.", file=sys.stderr)
        return 1
    for sub in ("assets/fonts", "assets/images", "layouts", "reference"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    theme, major, minor = _theme(prs)
    slide_w, slide_h = prs.slide_width, prs.slide_height
    scan = _scan_slides(prs)
    from_slides = _is_default_office(theme, major, minor) and bool(scan["text_colors"] or scan["faces"])

    # ---- colours
    dk1, lt1 = theme.get("dk1", "#14171c"), theme.get("lt1", "#ffffff")
    dk2, lt2 = theme.get("dk2", dk1), theme.get("lt2", "#f6f7f9")
    accent = theme.get("accent1", "#2f6df6")
    bg, fg = lt1, dk1
    muted = mix(fg, bg, 0.45)
    line = mix(bg, fg, 0.12)
    panel = lt2 if lt2 != bg else mix(bg, fg, 0.04)
    d_bg = mix(dk2, "#000000", 0.4)
    d_fg = lt2 if luminance(lt2) > 0.6 else "#eef1f4"
    d_accent = accent if contrast(d_bg, accent) >= 3 else mix(accent, "#ffffff", 0.3)
    palette = [theme[k] for k in ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6") if k in theme]
    if from_slides:
        def hexed(v: str) -> str:
            return "#" + v.lower()

        def chroma(v: str) -> float:
            r, g, b = hex_rgb(v)
            return (max(r, g, b) - min(r, g, b)) / 255

        counts = scan["text_colors"] + scan["fills"]
        usable = [hexed(c) for c, _ in counts.most_common() if c.lower() not in ("ffffff", "000000")]
        chromatic = [c for c in usable if chroma(c) > 0.12]
        if chromatic:
            # The heading colour is the one used at the largest text size.
            big = max(scan["size_color"], key=float, default=None)
            heading_color = hexed(scan["size_color"][big].most_common(1)[0][0]) if big else chromatic[0]
            accent = heading_color if chroma(heading_color) > 0.12 else chromatic[0]
            # Body text is the colour used at the text size that carries the most characters.
            body_size = max(scan["size_color"], key=lambda s: sum(scan["size_color"][s].values()), default=None)
            body = hexed(scan["size_color"][body_size].most_common(1)[0][0]) if body_size else dk1
            fg = body if contrast(bg, body) >= 4.5 else dk1
            palette = [accent] + [c for c in usable if c != accent][:3]
            palette += [mix(accent, "#ffffff", 0.45), mix(accent, "#ffffff", 0.75)][: 6 - len(palette)]
            muted = mix(fg, bg, 0.4)
            panel = mix(bg, accent, 0.06)
            line = mix(bg, accent, 0.18)
            dk2 = mix(accent, "#000000", 0.62)
            d_bg = dk2
            d_fg = mix("#ffffff", accent, 0.08)
            d_accent = accent if contrast(d_bg, accent) >= 3 else mix(accent, "#ffffff", 0.45)

    # ---- what the slides actually use
    backgrounds: dict[str, int] = {}
    layout_use: dict[str, int] = {}
    for slide in prs.slides:
        color = _slide_background(slide)
        if color:
            backgrounds[color] = backgrounds.get(color, 0) + 1
        layout_use[slide.slide_layout.name] = layout_use.get(slide.slide_layout.name, 0) + 1
    title_bg = ""
    first = prs.slides[0] if len(prs.slides) else None
    if first is not None:
        title_bg = _slide_background(first) or ""
    title_fg = "#ffffff"
    if title_bg:
        title_fg = "#ffffff" if contrast(title_bg, "#ffffff") >= contrast(title_bg, dk1) else dk1
        # A colour set directly on the cover's title text beats the guess above.
        for shape in first.shapes:
            if not shape.has_text_frame:
                continue
            found = None
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    try:
                        if run.font.color and run.font.color.type is not None and run.font.color.rgb is not None:
                            found = "#" + str(run.font.color.rgb).lower()
                    except (AttributeError, ValueError):
                        pass
                    if found:
                        break
                if found:
                    break
            if found:
                title_fg = found
                break

    # ---- logo: the smallest picture on the master or a layout, else a small picture that repeats near the edge of the slides
    logo_rel, logo_where, logo_text, logo_height = "", "top-right", "", "5.5vmin"
    n_slides = max(scan["slide_count"], 1)
    repeating = {d: e for d, e in scan["pictures"].items() if len(e["slides"]) >= max(2, 0.4 * n_slides)}
    candidates = list(_picture_shapes(prs.slide_master.shapes))
    for layout in prs.slide_layouts:
        candidates += list(_picture_shapes(layout.shapes))
    candidates = [c for c in candidates if c.width and c.height]
    if candidates and not from_slides:
        pic = min(candidates, key=lambda c: c.width * c.height)
        ext = "." + (pic.image.ext or "png")
        (folder / "assets" / f"logo{ext}").write_bytes(pic.image.blob)
        logo_rel = f"assets/logo{ext}"
        cx, cy = (pic.left + pic.width / 2) / slide_w, (pic.top + pic.height / 2) / slide_h
        logo_where = ("top" if cy < 0.5 else "bottom") + "-" + ("left" if cx < 0.5 else "right")
        logo_height = f"{max(3.5, min(9.0, 100 * pic.height / slide_h * 0.75)):.1f}vmin"
    else:
        edge = {d: e for d, e in repeating.items() if (e["cy"] < 0.25 or e["cy"] > 0.75) and e["area"] < 0.05}
        if edge:
            digest = min(edge, key=lambda d: edge[d]["area"])
            entry = edge[digest]
            if entry["svg"]:
                (folder / "assets" / "logo.svg").write_bytes(entry["svg"])
                logo_rel = "assets/logo.svg"
            else:
                (folder / "assets" / f"logo.{entry['ext']}").write_bytes(entry["blob"])
                logo_rel = f"assets/logo.{entry['ext']}"
            logo_where = ("top" if entry["cy"] < 0.5 else "bottom") + "-" + ("left" if entry["cx"] < 0.5 else "right")
            logo_height = f"{max(3.5, min(9.0, 100 * entry['h'] * 0.75)):.1f}vmin"
            # A short text that repeats right beside the mark is the wordmark.
            for label, info in scan["texts"].items():
                if len(info["slides"]) >= max(2, 0.4 * n_slides) and len(label) <= 30 and abs(info["cy"] - entry["cy"]) < 0.05 and abs(info["cx"] - entry["cx"]) < 0.12:
                    logo_text = label
                    break

    # ---- decoration that repeats on the slides (line art, ornaments), other than the logo
    decor_count = 0
    for digest, entry in repeating.items():
        if logo_rel and entry["area"] < 0.05 and (entry["cy"] < 0.25 or entry["cy"] > 0.75) and (folder / logo_rel).read_bytes() in (entry["svg"], entry["blob"]):
            continue
        decor_count += 1
        if entry["svg"]:
            (folder / "assets" / f"decor-{decor_count}.svg").write_bytes(entry["svg"])
        else:
            (folder / "assets" / f"decor-{decor_count}.{entry['ext']}").write_bytes(entry["blob"])

    # ---- pictures used on slides (photos and illustrations, not decoration that repeats)
    image_count = 0
    kept: set[str] = set()
    for digest, entry in scan["pictures"].items():
        if digest in repeating or entry["area"] < 0.04 or image_count >= 12 or entry["ext"] not in ("png", "jpg", "jpeg", "webp", "gif"):
            continue
        kept.add(digest)
        image_count += 1
        (folder / "assets" / "images" / f"image-{image_count:02d}.{entry['ext']}").write_bytes(entry["blob"])
    for slide in prs.slides:
        for pic in _picture_shapes(slide.shapes):
            if pic.width * pic.height < 0.12 * slide_w * slide_h:
                continue
            digest = hashlib.sha1(pic.image.blob).hexdigest()[:10]
            if digest in kept or digest in repeating or image_count >= 12:
                continue
            kept.add(digest)
            image_count += 1
            (folder / "assets" / "images" / f"image-{image_count:02d}.{pic.image.ext or 'png'}").write_bytes(pic.image.blob)

    # ---- fonts
    if from_slides and scan["faces"]:
        biggest = max(scan["sizes"], key=lambda f: (scan["sizes"][f], scan["faces"][f]))
        major, minor = _family_of(biggest), _family_of(scan["faces"].most_common(1)[0][0])
    fonts: dict[str, Any] = {}
    for role, family in (("heading", major), ("body", minor)):
        if not family:
            continue
        entry: dict[str, Any] = {"family": family, "files": {}, "fallback": FALLBACK_SANS}
        if family.lower() in SYSTEM_FONTS:
            entry["system"] = True
        elif args.fetch_fonts:
            if role == "body" and family == major and "files" in fonts.get("heading", {}):
                entry["files"] = fonts["heading"]["files"]
            else:
                entry["files"] = _fetch_font(family, folder / "assets" / "fonts")
        fonts[role] = entry

    # ---- layout catalogue and screenshots
    layouts_lines = []
    for layout in prs.slide_layouts:
        kinds = sorted({str(ph.placeholder_format.type).split(".")[-1].split(" ")[0].lower() for ph in layout.placeholders})
        layouts_lines.append(f"- {layout.name}: {', '.join(kinds) or 'no placeholders'}" + (f" (used on {layout_use[layout.name]} slide(s))" if layout.name in layout_use else ""))
    shots = 0 if args.no_screenshots else _render_screenshots(source, folder / "reference", args.max_slides)

    cfg = {
        "name": name,
        "description": f"Imported from {source.name}. Edit this line to say who the brand is for.",
        "mode": "light",
        "colors": {
            "accent": accent, "bg": bg, "fg": fg, "muted": muted, "line": line, "panel": panel,
            "title_bg": title_bg, "title_fg": title_fg,
            "dark": {"accent": d_accent, "bg": d_bg, "fg": d_fg, "muted": mix(d_fg, d_bg, 0.45), "line": mix(d_bg, d_fg, 0.14), "panel": mix(d_bg, d_fg, 0.06)},
        },
        "palette": palette,
        "fonts": fonts,
        "logo": {"file": logo_rel, "where": logo_where, "height": logo_height, "text": logo_text},
        "footer": "",
        "layouts": [],
    }
    (folder / "brand.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    bg_line = ", ".join(f"{c} ({n} slide{'s' if n > 1 else ''})" for c, n in sorted(backgrounds.items(), key=lambda kv: -kv[1])) or "none read"
    guide = f"""# {name}: look and feel

Imported from `{source.name}` on a machine, then to be edited by a person. Keep it short:
the agent reads this file every time a deck uses this brand.

## Read from the original (facts)
- Slide size: {slide_w / 914400:.2f} x {slide_h / 914400:.2f} in
- Accent colours in order: {', '.join(palette)}
- Slide background colours seen: {bg_line}
- Cover: background {title_bg or 'not read'}, text {title_fg}
- Headings font: {major or 'not read'}. Body font: {minor or 'not read'}
- Logo: {'`' + logo_rel + '`' + (' with the text "' + logo_text + '"' if logo_text else '') + ', placed ' + logo_where if logo_rel else 'none found'}
- Text that repeats on most slides: {', '.join('"' + k + '"' for k, v in scan['texts'].items() if len(v['slides']) >= max(2, 0.4 * scan['slide_count'])) or 'none'}

## Layouts in the original
{chr(10).join(layouts_lines)}

## Layouts to use in folio
- Cover: `{{layout=title}}`
- Agenda or three pillars: `{{layout=cards}}`
- Key numbers: `{{layout=stats}}`
- Picture and text: `{{layout=split}}`
- Everything else: the default

## To fill in by a person (a file cannot tell these)
- Look: one sentence on the feel and what to avoid.
- Imagery: what kind of pictures to use.
- Colour use: what the accent is for, what never goes together.
- Writing: tone, maximum bullets per slide, names that must never appear (also add them to forbid.txt).

## Reference
`reference/overview.png` shows every original slide on one sheet. Look at it only when building a
new layout.
"""
    (folder / "guidelines.md").write_text(guide, encoding="utf-8")
    description = f"""summary: TODO one line on the look and when to use it (read from the file: {major or 'system'} and {minor or 'system'} type, accent {accent}{', ' + str(image_count) + ' photographs' if image_count else ''}).

# {name}

## Look and feel
- TODO mood, colours, type, imagery. Facts read from the file: headings {major or 'not read'}, body {minor or 'not read'}, accent {accent}, {image_count} picture(s) kept, logo {'yes' if logo_rel else 'no'}, {len(prs.slides)} sample slide(s).

## Good for
- TODO the kinds of presentation this suits (audience and purpose).

## Not for
- TODO what it handles badly.

## Layouts and structures
- TODO layouts defined in layouts/*.css and what each is for. The original used: {', '.join(sorted(layout_use)) or 'none'}.

## Widgets
- TODO which interactive pieces work well here, and any limits.

## Typical outlines
- TODO name: slide, slide, slide.
"""
    (folder / "description.md").write_text(description, encoding="utf-8")
    (folder / "forbid.txt").write_text("# One name per line. Prefix with exact: for case-sensitive matching.\n", encoding="utf-8")
    (folder / "README.md").write_text(README.format(name=name, slug=slug), encoding="utf-8")

    print(f"Created brand '{slug}' in {folder}")
    print(f"  colours: accent {accent}, background {bg}, text {fg}; cover {title_bg or 'n/a'}")
    print(f"  fonts: heading {major or '-'}, body {minor or '-'}" + ("" if args.fetch_fonts else "  (add --fetch-fonts to download open-licence fonts)"))
    print(f"  logo: {logo_rel or 'none found'}   decoration: {decor_count}   images kept: {image_count}   screenshots: {shots}")
    print("Next: fill in the TODO lines in description.md and guidelines.md (a file cannot tell these), then run: check " + slug)
    for font in fonts.values():
        if font.get("family") and not font.get("system") and not font.get("files"):
            print(f"  note: '{font['family']}' will fall back to a system font until you add its .woff2 file. Embed only fonts you are licensed to share.")
    return 0


# ---------------------------------------------------------------- pull from git

def _clone_url(repo: str) -> tuple[str, str]:
    """Return (url to use, url safe to print). Accepts user/repo, a full URL or a local path."""
    if Path(repo).expanduser().exists():
        return str(Path(repo).expanduser()), str(Path(repo).expanduser())
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        repo = f"https://github.com/{repo}.git"
    shown = repo
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and repo.startswith("https://github.com/"):
        repo = repo.replace("https://", f"https://x-access-token:{token}@", 1)
    return repo, shown


def cmd_pull(args: argparse.Namespace) -> int:
    """Copy a templates repo to a local cache and remember it, so builds find it without flags."""
    if not shutil.which("git"):
        print("git is not installed here. Download the repo as a zip, unpack it and use --home.", file=sys.stderr)
        return 1
    url, shown = _clone_url(args.repo)
    cache_root = Path(os.environ.get("FOLIO_CACHE", Path.home() / ".folio" / "repos")).expanduser()
    target = cache_root / slugify(shown.replace("https://github.com/", "").removesuffix(".git"))
    cache_root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if (target / ".git").exists():
        result = subprocess.run(["git", "-C", str(target), "pull", "--ff-only", "--quiet"], capture_output=True, text=True, env=env, timeout=300)
        action = "Updated"
    else:
        command = ["git", "clone", "--depth", "1", "--quiet"] + (["--branch", args.ref] if args.ref else []) + [url, str(target)]
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=300)
        action = "Cloned"
    if result.returncode != 0:
        message = (result.stderr or result.stdout).replace(url, shown).strip()
        print(f"Could not fetch {shown}:\n{message}\n", file=sys.stderr)
        print("If the repo is private, set GITHUB_TOKEN (a token with read access to it) or download the repo as a zip, unpack it and use --home.", file=sys.stderr)
        return 1
    home = next((c for c in [target, *sorted(p for p in target.glob("*") if p.is_dir())] if (c / "brands").is_dir()), None)
    if home is None:
        print(f"{action} {shown}, but no brands/ folder was found in it. Expected the layout described in references/brands.md.", file=sys.stderr)
        return 1
    pointer = Path.home() / ".folio"
    pointer.mkdir(parents=True, exist_ok=True)
    (pointer / "home").write_text(str(home), encoding="utf-8")
    names = sorted(p.name for p in (home / "brands").iterdir() if (p / "brand.json").exists())
    print(f"{action} {shown}")
    print(f"Templates folder: {home}")
    print("Brands: " + (", ".join(names) or "none yet") + "   (builds now use this folder automatically)")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description="folio brand folders")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create an empty brand folder")
    p.add_argument("name")
    p.add_argument("--home")
    p.set_defaults(run=cmd_init)

    p = sub.add_parser("import-pptx", help="draft a brand folder from a PowerPoint file")
    p.add_argument("file")
    p.add_argument("--name")
    p.add_argument("--home")
    p.add_argument("--fetch-fonts", action="store_true", help="download open-licence fonts from Fontsource (needs npm)")
    p.add_argument("--no-screenshots", action="store_true")
    p.add_argument("--max-slides", type=int, default=30)
    p.add_argument("--force", action="store_true")
    p.set_defaults(run=cmd_import)

    p = sub.add_parser("list", help="show brands, decks and widgets in the templates folder")
    p.add_argument("--home")
    p.add_argument("--details", action="store_true", help="also print each description.md, to choose a brand for a request")
    p.set_defaults(run=cmd_list)

    p = sub.add_parser("check", help="check a brand for missing files and low contrast")
    p.add_argument("name")
    p.add_argument("--home")
    p.set_defaults(run=cmd_check)

    p = sub.add_parser("pull", help="fetch a templates repo from git (user/repo, URL or local path) and use it")
    p.add_argument("repo")
    p.add_argument("--ref", help="branch or tag")
    p.set_defaults(run=cmd_pull)

    p = sub.add_parser("where", help="print the templates folder in use")
    p.add_argument("--home")
    p.set_defaults(run=lambda a: print(find_home(a.home)) or 0)

    args = parser.parse_args()
    try:
        return args.run(args)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
