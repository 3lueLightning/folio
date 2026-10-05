# Widgets: custom animated or interactive pieces

Use a widget whenever the document needs something Markdown cannot express: an
animated diagram, a live timeline, a calculator, a chart that builds up step by
step, a map. **Never hand-write the whole deck as HTML because one slide needs
this.** Write the one piece as a widget and keep everything else Markdown, so
the template, edit mode, navigation, theme toggle and leak check all still work.

A widget is a small standalone HTML file (or an inline block). It runs inside a
sandboxed frame with no network and no access to the rest of the page.

## Using one

Beside the source, as a file (preferred for anything over about 15 lines):

```markdown
![One bottleneck, followed through the pipeline](widgets/order-flow.html){height=88 steps=2 orders=180}
```

Inline:

````markdown
```widget height=60 steps=2
<div id="x"></div>
<script>
  folio.onStep(function (s) { document.getElementById('x').textContent = 'Step ' + s; });
</script>
```
````

Parameters go in `{...}` (file form) or after `widget` (inline form).

| Param | Meaning |
| --- | --- |
| `height=N` | Slides: percent of the slide's content height (default 56). Page: N x 7 px. |
| `steps=N` | Number of extra steps after the first view. Arrow, space or swipe advances the widget before it moves to the next slide. Dots appear under it. |
| anything else | Free parameters. Read them in the widget with `folio.param('delay', 80)`. Values are strings. |

For a full-slide widget leave out the `#` title and use `height=88` or more.
Put the title inside the widget so it can change with the steps.

## What the widget can use

The frame gets a stylesheet with theme variables, so the widget matches light
and dark automatically: `--bg --fg --muted --line --panel --accent --serif
--sans --mono`. Use them instead of fixed colors. Leave `body` background
transparent.

The `folio` object:

| Member | Use |
| --- | --- |
| `folio.param(name, fallback)` | read a parameter |
| `folio.step`, `folio.steps` | current step (0 to steps) and the total |
| `folio.onStep(fn(step, prev))` | called when the step changes, including the first view |
| `folio.goto(n)` | jump to a step |
| `folio.setSteps(n)` | change the step count at runtime |
| `folio.onActivate(fn)` / `onDeactivate(fn)` | slide became or stopped being visible. Pause animation loops in deactivate. |
| `folio.active` | boolean |
| `folio.theme`, `folio.onTheme(fn)` | `"light"` or `"dark"` and a change hook |

Going backwards into a slide lands on its last step. Printing shows the last
step. Respect `prefers-reduced-motion`.

## Pictures and sound inside a widget

Write `{{asset:media/icon.svg}}` anywhere in the widget (an `src`, a JS string,
a CSS `url()`). The build replaces it with that file's bytes as a `data:` URI,
compressing images the same way as page media. The path is relative to the
`.md` source. Use it for icons, photos, a click sound (`new Audio("{{asset:media/tick.wav}}")`)
and so on. The file stays inside the one HTML output.

## Clicking and dragging

Mouse and touch work inside a widget as in any web page. For dragging use
pointer events (`pointerdown`, `pointermove`, `pointerup`) with
`setPointerCapture` and `touch-action:none` on the draggable element.
Keep the dragged element in a variable on `pointerdown`, move it with
`transform` on `pointermove`, and decide where it landed on `pointerup`.
Reject invalid drops by animating the element back and saying why.

## Click for details

`references/examples/widgets/order-flow.html` opens a small card (`#pop`) when a
stage is clicked. Position it from `getBoundingClientRect()` of the clicked
element and close it on any other click. Numbers come from parameters
(`orders`, `packers`), so they can be changed in the deck source without
touching the widget.

## Rules

1. **Self-contained.** No `http(s)` URLs, no CDN scripts, no web fonts, no
   fetch. The sandbox blocks them and the build warns. Inline SVG, canvas and
   plain JS cover almost everything. Small images may be `data:` URIs.
2. **Compute, do not hard-code.** Derive numbers and captions from the data in
   the widget, so changing one parameter updates every label.
3. **Build a working step 0.** The first view must make sense with no clicks.
4. **Keep it light.** Under about 50 kB of HTML. Animate transform and opacity.
   Stop loops when inactive.
5. **Fictional data only** for public demos, and never real company names.

## Reference

`references/examples/widgets/order-flow.html` is a complete worked widget: a
four-stage pipeline with capacities, a live slider, three steps, a click-for-details
card and a flow animation that stops when the slide is hidden. Copy it as a
starting point for any flow, pipeline, network or what-if diagram and change the
data and wording. `references/examples/widget-demo.md` shows it inside a deck.

## When the source must not mention certain names

Pass `--forbid "Name1,Name2"` to the build. It scans slide text, notes, header
fields, widget code and media file names, and refuses to write the file if
anything matches. Pictures are not scanned: look at them yourself.
