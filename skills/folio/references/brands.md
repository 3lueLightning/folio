# Brands: templates in the user's own folder

## Folder layout

```
<home>/                      $FOLIO_HOME, --home, the nearest parent holding brands/, or ~/folio-templates
  brands/<name>/
    brand.json               colours, fonts, logo, footer. Edit the values, keep the keys
    description.md           what it looks like and suits: look and feel, good for, not for, layouts, widgets, typical outlines (under 2 kB)
    guidelines.md            the rules for writing a deck with it, under 4 kB. The agent reads this once a brand is chosen
    forbid.txt               names that must never appear (one per line, "exact:" prefix for case-sensitive)
    assets/fonts/*.woff2     only fonts the user is licensed to embed
    assets/logo.png          referenced from brand.json
    layouts/*.css            extra layouts, used as {layout=name}; style .slide.layout-name
    reference/               screenshots of the original slides (overview.png is a contact sheet)
  decks/<name>/deck.md       past decks, reusable as a starting point (copy, then edit)
  decks/<name>/description.md  optional: summary line, what it is good as a starting point for, structure
  widgets/                   widgets worth reusing. A first-line comment <!-- description: ... --> is shown by list
```

`python scripts/folio_brand.py init NAME` creates the brand part of this tree.

## description.md: how the agent chooses a brand

When a request names no brand, the agent runs `list --details` and picks from these files, so they decide
whether the right template is found. Keep each under about 2 kB. The first line is `summary: ...` (one
sentence, shown by plain `list`). Then the sections Look and feel, Good for, Not for, Layouts and structures,
Widgets and Typical outlines. Be specific about audience and purpose ("sales decks for external audiences")
rather than adjectives alone. `init` creates a skeleton, `import-pptx` drafts one from the file with TODO lines
for what only a person knows, and `check` flags placeholders or a missing file. Past decks can carry the same file.

## What brand.json controls

- `colors`: accent, bg, fg, muted, line, panel, plus `title_bg` and `title_fg` for the cover and a `dark` block for the dark theme.
- `palette`: up to six more colours, available in layout CSS as `var(--c1)` to `var(--c6)`.
- `fonts.heading` and `fonts.body`: family, `files` (weight to .woff2 path) and a fallback stack. Widgets receive the same fonts.
- `logo`: file, `where` (top-right, top-left, bottom-right, bottom-left), `height` (CSS length), optional `text` (a name set in the heading font beside the picture).
- `footer`: default footer text. `mode`: default theme (`light` or `dark`) when the deck header has none.

A deck header can still set `theme`, `accent` or `footer`; those win over the brand.

## Writing layout CSS

Layout files are plain CSS appended after the built-in styles. A new layout `closing` is
selected by `{layout=closing}` and styled with `.slide.layout-closing`. Built-in layouts
(title, split, split-left, full, center, cards, stats, default) can be restyled the same way.
Use CSS variables (`var(--accent)`, `var(--fg)`, `var(--panel)`, `var(--c2)`) so the dark theme
keeps working, and test both themes. Images inside layout CSS use `{{asset:assets/x.png}}`.
Sizes in `cqw` and `cqh` scale with the slide.

## Importing from PowerPoint

```bash
python scripts/folio_brand.py import-pptx corporate.pptx --name acme --fetch-fonts
```

Captured: colours, heading and body fonts, the logo (and its name, when text repeats beside it), line art
that repeats on the slides, the cover background, large photographs, layout names and slide screenshots
(needs LibreOffice for the screenshots). Files exported from Canva and similar tools keep PowerPoint's stock
theme and draw the design in the slides, so for those the importer reads colours, fonts and the recurring
logo from the slides themselves. Corner shapes and other drawn ornaments are not images: recreate them in
`layouts/*.css`, using `reference/overview.png` as the guide. `--fetch-fonts` downloads open-licence fonts from
Fontsource when the family exists there. Fonts that are not open-licence (most corporate fonts)
stay system fonts: install them on each machine or add licensed .woff2 files by hand.

Not captured: tone of voice, rules for when to use which layout, picture style, what must never
be said. Those go in `guidelines.md`, written by a person. Screenshots help when designing a new
layout but cannot replace the written rules.

## Keeping the folder in a Git repo

Make the repo root the templates folder (`brands/`, `decks/`, `widgets/` at the top). Commit `.folio-cache`
to `.gitignore`. Then, in any session:

```bash
python scripts/folio_brand.py pull user/repo        # or a full URL, or a local path; --ref for a branch
```

`pull` makes a shallow clone in `~/.folio/repos`, remembers it in `~/.folio/home` and prints the brands it
found. Running it again updates the clone. A private repo needs a read-only token in `GITHUB_TOKEN`; without
one, download the repo as a zip, unpack it and pass `--home`. Keep the repo private: it holds `forbid.txt`
(client names) and photographs and fonts with their own licences.

## Sharing

Check the firm's rules before sharing a corporate template or its fonts. Do not redistribute
third-party template files. `forbid.txt` is the place for client and competitor names; keep it in the
user's folder, not in the plugin.
