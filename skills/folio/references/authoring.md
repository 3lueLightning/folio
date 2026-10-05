# Writing a folio source file

The source is ordinary Markdown with a small header and a few conventions. It
stays readable on its own, which matters because it is what gets edited and
what goes into version control.

## Header

The header sits between two `---` lines at the very top.

```markdown
---
title: Quarterly Review
subtitle: Where the numbers came from
format: slides
theme: light
accent: #2f6df6
footer: Internal - September 2026
---
```

| Key | Values | Meaning |
| --- | --- | --- |
| `title` | any text | browser tab, and the heading in page format |
| `subtitle` | any text | shown under the title in page format |
| `format` | `slides` or `page` | 16:9 slides you page through, or a scrolling document |
| `theme` | `light` or `dark` | starting theme, the reader can switch with `T` |
| `accent` | a hex colour | bullets, links, progress bar, quote rules |
| `footer` | any text | small line in the corner of every slide |

Only `title` is required. Switching `format` between `slides` and `page`
changes nothing else, so the same source works both ways.

## Sections

A section is one slide in `slides` format and one block in `page` format.
Sections are separated by a line containing only `---`, and a `#` heading also
starts one.

```markdown
# The first section

Some text.

---

# The second section
```

## Layouts

Add a layout in braces after the heading.

```markdown
# Opening {layout=title}
```

| Layout | What it does |
| --- | --- |
| (none) | heading at the top, content below |
| `title` | everything centred, large heading, for an opening or closing slide |
| `center` | content centred, normal heading size |
| `split` | text on the left, media on the right |
| `split-left` | media on the left, text on the right |
| `full` | media fills the slide, text sits on top with a dark gradient behind it |

In a split layout you do not need to order things carefully. Media goes to the
media column and everything else to the text column, whatever order you write
them in.

Layouts only affect `slides` format. In `page` format everything becomes a
normal flowing document.

## Media

Images, video and audio all use the same form. The file extension decides which
is which.

```markdown
![A caption](media/chart.png)
![Demo recording](media/clip.mp4)
![Narration](media/voice.wav)
```

Paths are relative to the source file. Leave the caption empty (`![](...)`) if
you do not want one.

Supported: png, jpg, gif, webp, avif, svg, bmp for images; mp4, webm, mov, m4v,
mkv, avi for video; mp3, wav, m4a, ogg, opus, flac, aac for audio. Video and
audio get a player with controls. The same file used twice is only embedded
once.

An animated GIF is passed through untouched, because converting it would drop
the animation. Animated GIFs are large, so prefer a short mp4.

## Text

Standard Markdown inside a section:

- `**bold**`, `*italic*`, `` `code` ``, `~~strikethrough~~`, `==highlight==`
- `[link text](https://example.com)`
- `-` or `*` for bullets, `1.` for a numbered list
- `##` and `###` for headings inside a section
- `>` for a block quote
- Fenced code blocks with triple backticks
- Pipe tables with a header row and a `---` separator row

Attribute a quote by ending it with a dash line:

```markdown
> We profiled far too late in the project.
> - Post-mortem note
```

## Cards, stats and sound

`{layout=cards}` turns a bullet list into a row of cards and `{layout=stats}`
into big numbers. Start each bullet with a bold label and no colon. Add
`sound: media/ambient.mp3` to the header for a background loop the audience
can start with `M`.

## Widgets

Custom animated or interactive pieces use `![caption](widgets/x.html){height=90 steps=3}`
or a fenced `widget` block. Full guide: `widgets.md`. Omit the `#` title on a
slide that is only a widget.

## Speaker notes

A line starting with `Note:` becomes a speaker note for that section. It never
appears on the slide. The reader presses `N` to show notes.

```markdown
Note: Keep this to two minutes. The detail is in the appendix.
```

Notes are ignored in `page` format.

## A worked example

```markdown
---
title: Search Latency Review
format: slides
accent: #2f6df6
---

# Search Latency Review {layout=title}

Where the 2.4 second median came from.

Note: Fifteen minutes, then questions.

---

# Where the time went {layout=split}

![Weekly throughput](media/chart.png)

The median request spent most of its life waiting.

- Embedding call, **1.3 seconds**
- Vector search, 0.6 seconds
- Reranking, 0.4 seconds

---

## The three numbers

| Stage | Before | After |
| --- | --- | --- |
| Embedding | 1.3 s | 0.2 s |
| Vector search | 0.6 s | 0.5 s |

---

# What we changed

```python
async def embed(query: str) -> list[float]:
    cached = await cache.get(normalise(query))
    return cached if cached is not None else await client.embed(query)
```

Twenty lines and one Redis instance.
```

## Things that will not work

- HTML inside the source. It is escaped and shown as text, deliberately.
- Absolute paths or URLs for media. Everything has to be a local file, or it
  cannot be embedded.
- Nested bullets. Flatten them, or use a heading and a second list.
- Footnotes, task lists and definition lists.

## Folder layout

```
my-deck/
  deck.md
  media/
    chart.png
    clip.mp4
  deck.html          <- built output
  .folio-cache/    <- compressed media, safe to delete
```

Commit `deck.md` and `media/`. Ignore `deck.html` and `.folio-cache/`; both
are rebuilt from the source in under a second.
