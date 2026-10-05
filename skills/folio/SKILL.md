---
name: folio
description: Build a self-contained single-file HTML document, presentation, note collection or mini-site with embedded images, video, audio, interactive widgets, brand templates and an in-browser edit mode. Use for any request for a deck, slides, demo presentation, rich document or report as HTML, especially with animation, interactive elements, diagrams or media, or when it must be shared as one file that opens by double-clicking. Also when they mention folio.
---

# Folio

Documents, presentations, notes and mini-sites as one file. Produces one `.html` file that holds the text, the styling, the interaction and
every image, video and audio clip. It opens by double-clicking in any browser.
There is no folder of assets to send alongside it and no server to run.

## Why the source is Markdown and not HTML

You write a small Markdown file. A build script renders it into the template,
which already contains the styling, the navigation, the edit mode and the save
logic. You never write or read the HTML.

Follow that split. Writing HTML by hand for these documents costs roughly five
times the tokens and loses edit mode and save. To change one sentence, edit
that line of the `.md` file and rebuild. Do not open the built `.html`.

**Custom animation or interactivity is not a reason to leave folio.** Write
just that piece as a widget (a small HTML file, see `references/widgets.md`)
and reference it from the Markdown. The deck itself is always built from
Markdown. Never hand-write the deck page.

## Building one

```bash
python scripts/build_folio.py deck.md
```

Writes `deck.html` beside the source and prints the size of each media file
before and after compression, plus a warning if the result is too big to email.

Useful flags:

| Flag | Effect |
| --- | --- |
| `-o path.html` | write the output somewhere else |
| `--video-crf 34` | smaller video, lower quality (18 is near-lossless, 30 is the default) |
| `--video-width 960` | scale video down further |
| `--image-quality 70` | smaller images |
| `--apply changes.json` | fold in edits someone made in the browser |
| `--write-source` | with `--apply`, also update the `.md` source |
| `--brand name` / `--home dir` | use a brand (overrides the header) and say where the templates folder is |

## Writing the source

Full syntax is in `references/authoring.md`. Read it before writing a source
file for the first time. The short version:

````markdown
---
title: Quarterly Review
subtitle: Where the numbers came from
format: slides        # or "page" for a scrolling document
theme: light          # or dark
accent: #2f6df6
footer: Internal - September 2026
---

# Opening slide {layout=title}

One line that sets up the talk.

Note: Speaker notes go here. They never appear on the slide.

---

# A slide with a picture beside it {layout=split}

![Caption](media/chart.png)

- A point
- Another point

---

# A slide with video

![What it looks like](media/clip.mp4)
````

Sections are separated by `---`. A `#` heading starts a new section. Images,
video and audio all use the `![caption](path)` form and are told apart by file
extension. `Note:` lines become speaker notes.

Layouts: `title`, `split` (media right), `split-left` (media left), `full`
(picture fills the slide behind the text, good for a cover), `center`, `cards`
(each bullet becomes a card; start it with a bold label and no colon, like
`- **Anticipate** See it coming`), `stats` (same, with the bold part as a big
number: `- **91** passengers affected`), and the default.

Background sound: add `sound: media/ambient.mp3` to the header. A speaker button
appears in the toolbar and `M` toggles it. It never starts by itself, because
browsers block that and it startles a room.

## Animated and interactive pieces (widgets)

For a flow diagram, live timeline, calculator or any step-by-step animation:

```markdown
![Caption](widgets/my-diagram.html){height=90 steps=3}
```

The widget runs in a sandbox, picks up the theme, can show pictures and play sounds from the media folder (`{{asset:path}}`), can be clicked and dragged, and the arrow keys step
through it before moving to the next slide. Read `references/widgets.md` before
writing one. `references/examples/widgets/order-flow.html` is a complete model (steps, slider, click for details, theme variables) and `references/examples/widget-demo.md` shows it inside a deck.

## Brands (templates that live in the user's own folder)

A brand is a folder with colours, fonts, a logo, extra layouts and a short
guidelines file. It lives in the user's own templates folder (`$FOLIO_HOME`,
often a Git repo), never in this skill. A deck uses one with `brand: name` in
its header. The brand sets colours, fonts, logo, footer, theme and its own
layouts, and its `forbid.txt` is added to the forbidden-name check.

When a request names a brand or the user has one:

0. If the user names a templates repo (for example `user/repo`) or no brands are found, run
   `python "$SKILL/scripts/folio_brand.py" pull user/repo`. It clones the repo and remembers it, so later
   builds find it without flags. If it cannot reach the repo (private, no network), ask the user to attach the
   repo as a zip, unpack it and pass `--home`.
1. Run `python "$SKILL/scripts/folio_brand.py" list --details`. Each brand and past deck has a short
   `description.md` (look and feel, good for, not for, layouts, widgets, typical outlines). If the user named
   no brand, choose the one whose "Good for" fits the audience and topic, say which and why in one line, and
   offer the runner-up. If none fits, build without a brand. A past deck that fits is a better starting point
   than a blank one: copy its `deck.md`. Do not open brand.json or the CSS.
2. Read only `brands/<name>/guidelines.md` (under 4 kB) and follow it. Do not read the other brand files.
3. Put `brand: <name>` in the deck header. Use only the layouts the guidelines list.
4. Build as usual. Add `--home <folder>` if `$FOLIO_HOME` is not set.

Other commands: `pull REPO` fetches a templates repo. `init NAME` creates an empty brand folder with the expected
structure. `import-pptx FILE --name NAME [--fetch-fonts]` reads colours, fonts, logo,
layouts and slide screenshots from a PowerPoint and writes a draft brand; a person
must still write the rules in `guidelines.md`. `check NAME` flags low contrast,
missing fonts or logo. `where` shows which folder is in use. Embed only fonts the
user is licensed to share. Read `references/brands.md` to create or edit a brand.

## When names must not appear

If the user says certain companies, people or words must not appear, add
`--forbid "A,B,C"` to every build (`--forbid-exact` for case-sensitive
acronyms). The build checks text, notes, widgets and file names and writes
nothing if there is a hit. Pictures are not checked, so look at them. Use
fictional data for anything shown to outside audiences.

## Tab icon and first view

The build makes the browser tab icon from the first picture in the document (or
the accent colour and the title's initial). The first slide is drawn with no entrance
animation, so previews and thumbnails taken at load show the cover. The file also carries a static copy of the cover that shows only where scripts
do not run (Quick Look, mail and Teams previews). Finder and File Explorer
icons for `.html` files come from the operating system and cannot be set from
inside the file.

## What the recipient can do

Arrow keys or swipe to move, `O` for an overview of all sections, `N` for
speaker notes, `T` for light or dark, `F` for full screen, `Ctrl+P` to print or
save as PDF. Pressing `E` turns on edit mode, where clicking any text edits it
in place. Changes are kept in the browser as they type, so closing the tab does
not lose them.

They cannot overwrite the file they opened, because no browser allows that.
Pressing `Ctrl+S` offers to copy their changes (a few kB of JSON) or download
them. Send that file back through `--apply`.

## Editing with save straight to the source

For the document's owner there is a better loop:

```bash
python scripts/serve_folio.py deck.md
```

This opens the document from `http://127.0.0.1:8777`, where the page can post
changes back. `Ctrl+S` then writes the Markdown source and rebuilds the HTML in
place, with no second copy and no version numbers piling up in the folder.
Nothing leaves the machine. Stop it with `Ctrl+C`; the built file keeps working
on its own.

## Keeping the file a sensible size

Text and images are cheap. Video is not.

| Asset | Roughly, after compression |
| --- | --- |
| Full-page screenshot | 40 to 150 kB |
| Photograph | 80 to 250 kB |
| Audio narration | 1 MB per minute |
| Video at 720p | 3 to 6 MB per minute |

Embedding inflates all of these by about a third, because binary data has to be
written as text. Two thresholds matter: most mail servers reject attachments
over 25 MB, and browsers get visibly slow to open a file past 50 MB. The build
warns at both. Share through Teams, SharePoint or OneDrive when a video-heavy
document goes over.

## Requirements

Python 3.9 or later and Pillow (`pip install pillow`) for images. ffmpeg is
needed only for video and audio; without it those files are embedded
uncompressed and the build says so. Windows, macOS and Linux all work.

## Checklist

1. Ask what the document is for and who receives it, unless it is obvious.
2. Write or update the `.md` source. Only the `.md`.
3. Put media in a folder beside it and reference it with a relative path.
4. Run the build. Read the size report.
5. Deliver the `.html` file itself with SendUserFile. Do not publish it as an
   artifact unless asked. Mention that pressing `E` lets them edit it.

## Locating the scripts

`$SKILL` is the folder holding this file. In Claude Code and Claude desktop it
is the skill's directory; in GitHub Copilot it is `.github/skills/folio` or
`~/.copilot/skills/folio`. Run `python "$SKILL/scripts/build_folio.py"`
with the path to the `.md`.
