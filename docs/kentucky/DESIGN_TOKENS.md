# Design Tokens (OT-01)

Derived from the kentucky-ai.com landing page and OpenTakeoff Premium's `styles/tokens.css`,
`premiumWorkspace.css`, `set.css`, `platform.css` and `feedback.css`. Only values were reproduced; no
proprietary files or artwork were copied. Implementation: `label_studio/kentucky/static/kentucky/ka.css`.

* **Principles**: cyan is the only accent; amber = needs you; coral = real errors only; hairlines over
  cards; no gradients on app surfaces (the tri-stripe is the single brand flourish); tabular numerals.
* **Type**: Inter Tight (display/body), Space Mono (labels, numbers). Scale 28/32, 20/26, 16/22, 14/20,
  13/18, 12/16. Captions: 600 12px, .04em, uppercase, muted.
* **Graphite (dark, default)**: paper `#0c0e0f`, card `#111415`, hover `#171b1c`, pop `#1b2021`,
  ink `#e8ecea` / `#c5ccca` / `#9ba4a1`, rule `#2f3739`, accent `#62d4dc`, positive `#7fcf9c`,
  warn `#f0b24a`, danger `#ff7b63`.
* **Light**: paper `#f2f4f3`, card `#fafbfb`, ink `#161a1b`, rule `#cfd6d3`, accent text `#0e636b`,
  positive `#2f6b42`, warn `#8a5a00`, danger `#b3321c`. Primary button fill stays `#62d4dc` with `#111` text.
* **Chrome**: top bar `#24292b` in every look, 52px; sidebar 252px (64px rail ≤ 1100px); nav items 36px
  with a 3px accent bar for the active item.
* **Spacing** 4px grid (4–56). **Radii** 6px controls, 10px dialogs, 999px chips. **Motion** 120–180ms
  `cubic-bezier(.16,1,.3,1)`, press = `translateY(1px)`.
* **Components**: title block page headers, `set-h` section rules, `set-table`, chips/tags, steps,
  toasts with 4px tone border, drafting-grid empty states with a self-drawing accent stroke, skeletons.
