# Folio: notes for Claude Code

Read this first in every session. It replaces the conversation history that produced the project. Keep it current:
when you change architecture, commands or decisions, update the matching section in the same commit.

## What this is

Folio turns a Markdown source into ONE self-contained `.html` file (text, styles, scripts, images, video, audio, fonts
all inline). It opens by double-click, works offline and has an in-browser edit mode. The target outputs are
presentations first, then documents, notes and mini-sites. Documents in a Word-like layout are not optimised yet.

One tree serves two uses: a Claude skill (`skills/folio/`) and a Claude plugin (the whole repo minus
`examples/`, `tools/`, this file). Users reach it from Claude chat, Claude Code or other agents.

## Why it exists (the design goal)

An agent that writes a deck as raw HTML must print the whole file, and must print it again for every edit. Folio keeps
the agent in Markdown: the agent writes and edits a small source file, a script builds the HTML, and the agent never reads
the built file. Cost per edit stays flat instead of growing with file size. Do not add features that make the agent read
built HTML.

## Layout

```
.claude-plugin/plugin.json      plugin manifest (bump version on every release)
skills/folio/SKILL.md           what the agent reads. Keep it short, push detail into references/
skills/folio/references/        authoring.md (syntax), widgets.md, brands.md, examples/ (one neutral widget and deck)
skills/folio/assets/template.html   the runtime: renderer, navigation, edit mode, save, widget host (one file)
skills/folio/scripts/
  build_folio.py                CLI entry: source -> html. Placeholders in the template are filled in one re.sub pass
  folio_model.py                Markdown <-> content model (JSON). Also merges edits back into Markdown
  folio_media.py                image, video, audio compression and base64 embedding
  folio_brand.py                brand folders: init, import-pptx, list, check, pull, where
  serve_folio.py                local server so Ctrl+S in the browser writes back to the .md
examples/                       full demo deck with photo, video, audio (repo only, not in the plugin)
tools/package.py                builds dist/folio.plugin and dist/folio-source.zip, scans for forbidden terms
```

Placeholders in `template.html`: `__(TITLE|MODEL|ASSETS|ICON|COVERSTYLE|COVER|BRANDCSS)__`, substituted in one pass so
substituted content is never re-scanned.

## Commands

```bash
python skills/folio/scripts/build_folio.py examples/demo-deck.md
python skills/folio/scripts/build_folio.py skills/folio/references/examples/widget-demo.md
python skills/folio/scripts/serve_folio.py examples/demo-deck.md        # edit in browser, Ctrl+S saves to .md
python skills/folio/scripts/folio_brand.py init NAME | import-pptx FILE --name NAME | list --details | check NAME | pull REPO | where
python tools/package.py --terms ../private/terms.txt                    # release build, see "Releasing"
```

Needs Python 3.9+ and Pillow. ffmpeg is optional. `python-pptx` and LibreOffice are needed only for brand import.

## Concepts you must not break

- **Single file output.** No external URLs, no fetches, no web fonts from a CDN. Everything is a `data:` URI.
  The build reports size and warns at 25 MB (mail limit) and 50 MB (slow to open).
- **Widgets** are sandboxed iframes (`srcdoc`, CSP blocks network). Theme variables are injected
  (`--bg --fg --muted --line --panel --accent --head --serif --sans --mono --c1..--c6`). API: `window.folio` with
  `param, step, steps, setSteps, goto, onActivate, onDeactivate, onStep, onTheme`. `{{asset:path}}` inlines a file as a
  data URI. Brand `@font-face` rules are re-injected into widgets.
- **Brands** live in the USER's own folder, never in this repo. Home is resolved in order: `--home`, `$FOLIO_HOME`,
  nearest parent containing `brands/`, `~/.folio/home` pointer (written by `pull`), `~/folio-templates`.
  A brand holds `brand.json`, `description.md` (so the agent can choose a brand), `guidelines.md` (under 4 kB),
  `forbid.txt`, `assets/`, `layouts/*.css`, `reference/`. A deck selects one with `brand: name`. Deck values for theme,
  accent and footer override the brand's.
- **Leak check.** `--forbid`, `--forbid-exact` and the brand's `forbid.txt` are scanned against text, notes, widget code
  and media file names. A hit fails the build and writes nothing. Forbidden names are NEVER hard-coded in this repo.
- **Importer** (`import-pptx`): reads theme colours and fonts. When the theme is stock Office it scans slide shapes
  instead (text colours by size, fonts, recurring pictures for the logo, recurring text for a wordmark). Fonts are fetched
  only from open-licence sources. It writes a draft `guidelines.md` and `description.md` with TODO lines for a person to finish.
- **Edit mode** (`E` key) edits the content model in the page. Save either downloads a new file or, through
  `serve_folio.py`, writes the Markdown back. Merging someone else's edits: `--apply changes.json --write-source`.

## Public repo rules (read before every commit)

This repository is public. Never commit:
- names of employers, clients, real companies, real products or people (other than the licence holder)
- real data of any kind. Examples use fictional names and numbers only
- local paths, usernames, email addresses, tokens, internal repository names
- third-party templates, fonts without a redistribution licence, or photos without one
- built `.html` output, caches, `dist/`, `CLAUDE.local.md`
Before a release run `tools/package.py` with a terms file kept OUTSIDE the repo. It refuses to package on any hit.
Do not add example content that matches a test or benchmark scenario, because bundled examples get reused by the agent
verbatim (this happened once with an image and invalidated a comparison run).

## Testing

There is no unit-test suite yet. Current practice: build both example decks, open them headless (Playwright with
Chromium) with the network blocked, step through slides, and check for console errors, blocked requests and layout
overflow. Adding a real test suite (pytest for `folio_model` round trips and the leak check, Playwright smoke test for
the runtime) is the first backlog item below.

## Backlog

1. Test suite and CI (GitHub Actions on Linux, Windows, macOS).
2. Verify on Windows and macOS: path separators, ffmpeg absent, port 8777 already in use for `serve_folio.py`.
3. Document and note layouts: a long-form `format: document` look (page width, headings, footnotes, table of contents,
   print and PDF stylesheet), and a notes format (many short linked entries, search).
4. Exact token measurement harness: replay a fixed list of prompts through the API with and without the skill,
   report input, output and cached tokens per turn.
5. Home page for the project, built with Folio itself, with a recorded side-by-side comparison.
6. Per-slide transitions and a presenter view.

## Working style for this project

- Plain prose in docs and commit messages. No em-dashes. Cause before effect. Units always written out.
- Keep SKILL.md short. The agent loads it on every trigger, so each line costs tokens for every user.
- Prefer small, reversible commits. Run both example builds before committing.
- Ask before changing the content model or the placeholder scheme, because saved user decks depend on them.
