# Folio

Documents, presentations, notes and mini-sites as one file. Write Markdown, get one self-contained HTML file in your own brand.
Images, video, audio, styling and interaction all live inside the single file,
so it opens by double-clicking and there is nothing to send alongside it.

## Install

- **Claude desktop or claude.ai:** upload `folio.plugin` (a zip of this repository, built with `python tools/package.py`).
- **Claude Code:** `claude --plugin-dir /path/to/this/repo`, or copy `skills/folio/` into `~/.claude/skills/`.
- **Any other agent or by hand:** the skill is only Markdown plus Python scripts. Point the agent at `skills/folio/SKILL.md`.

## Quick start

```bash
pip install pillow
python skills/folio/scripts/build_folio.py examples/demo-deck.md
```

Open `examples/demo-deck.html`. Arrow keys to move, `O` for an overview, `E` to
edit any text in place, `?` for the rest.

## The loop

```
deck.md  +  media/   ->   build_folio.py   ->   deck.html   (one file, share it)
```

To edit in the browser and have `Ctrl+S` write straight back to `deck.md`:

```bash
python skills/folio/scripts/serve_folio.py deck.md
```

To fold in changes someone else made in their copy:

```bash
python skills/folio/scripts/build_folio.py deck.md --apply their-changes.json --write-source
```

## Why one file

A presentation that loads images and stylesheets from a folder breaks the
moment it is emailed on its own. It also breaks in a subtler way: a browser
opening a page from disk refuses to fetch sibling files, so a deck that works
on your machine can silently fail on someone else's. Everything embedded avoids
both problems, at the cost of file size, which the build reports on every run.

## Contents

Paths are relative to `skills/folio/` unless they start with `examples/` or `tools/`.

| Path | What it is |
| --- | --- |
| `SKILL.md` | instructions for Claude |
| `references/authoring.md` | the full source syntax |
| `references/widgets.md` | animated and interactive pieces (sandboxed widgets) |
| `assets/template.html` | the runtime: renderer, navigation, edit mode, save |
| `scripts/build_folio.py` | the build command |
| `scripts/serve_folio.py` | local server for save-to-source editing |
| `scripts/folio_model.py` | Markdown to content model and back |
| `scripts/folio_media.py` | media compression and embedding |
| `scripts/folio_brand.py` | brand folders: init, import from PowerPoint, list, check |
| `references/brands.md` | how brands work and how to write one |
| `examples/demo-deck.md` (repository root) | a worked example using every feature, with photo, video and audio |
| `tools/package.py` (repository root) | builds `dist/folio.plugin` and checks the tree for names that must not ship |
| `references/examples/widget-demo.md` + `widgets/order-flow.html` | a deck with an animated, stepped diagram |

## Brands

A brand is a folder in your own templates folder (set `FOLIO_HOME`, for example a Git repo)
holding colours, fonts, a logo, extra layouts and a short `guidelines.md`. A deck uses it with one
header line, `brand: acme`. The plugin never contains a brand.

```bash
python skills/folio/scripts/folio_brand.py init acme                       # empty brand with the expected structure
python skills/folio/scripts/folio_brand.py import-pptx acme.pptx --name acme --fetch-fonts
python skills/folio/scripts/folio_brand.py check acme
python skills/folio/scripts/folio_brand.py pull user/templates-repo        # fetch your templates from Git
python skills/folio/scripts/folio_brand.py list --details                  # summaries, so the right brand can be chosen
```

Importing reads colours, fonts, logo, layouts and screenshots from a PowerPoint file. The rules
for tone, layout choice and imagery cannot be read from a file, so `guidelines.md` is written by a
person. Importing needs `pip install python-pptx` and, for screenshots, LibreOffice.

## Requirements

Python 3.9 or later, and Pillow for images. ffmpeg is optional and only used
for video and audio; without it those are embedded uncompressed. Windows, macOS
and Linux.

## Size

Two thresholds matter. Most mail servers reject attachments over 25 MB, and
browsers get slow opening a file past about 50 MB. The build warns at both.
Text and images stay small. Video is what pushes a file over, so keep clips
short or lower `--video-crf`.

## Licence

MIT. See `LICENSE`.
