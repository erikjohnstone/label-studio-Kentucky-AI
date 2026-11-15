# Design system (v5)

Built from seven research passes (Apple Design Award apps, AI/ML training products, design galleries,
canvas/annotation tools, Awwwards winners, best-in-class SaaS, construction tech) plus the kentucky-ai.com
landing page. Approved concepts live in `docs/kentucky/design/concepts/`. Implementation:
`label_studio/kentucky/static/kentucky/ka.css` (tokens + app components), `review.css` (Check screen).

## Principles
* Contractors first: plain words ("Check", "Keep", "Not a door"), one obvious next step per screen,
  the AI does the first pass and people approve.
* Light pages, dark drawing panels. The drawing canvas follows the theme (paper in Light, graphite blueprint in Dark).
* Two-tone headlines: the statement in ink, the context in a lighter tone ("Model v5 finds 10 of every 10 doors. /
  Tested on a sheet it never saw.").
* Cyan `#62d4dc` only for what is actionable or live. Status colour on dots and pills, never big fills.
* Hairlines and soft rings over heavy cards; mono instrument labels (`[ SHEET 02 / 07 ]`, `FOUND 8 OF 8`).
* Every number shown is measured; estimates are labelled as such.

## Tokens
| Token | Light | Dark |
|---|---|---|
| `--bg` | `#f4f5f5` | `#0a0c0e` |
| `--surface` | `#ffffff` | `#101316` |
| `--sunken` | `#eef0f1` | `#161a1e` |
| `--ink` / `-2` / `-3` / `-4` | `#0c1113` `#3a4449` `#69737a` `#9aa3a9` | `#f2f5f6` `#c4ccd3` `#8a939c` `#5d656d` |
| `--line` / `-2` | `#e3e6e8` `#d3d8db` | `#1e2327` `#2a3037` |
| `--teal` (accent text) | `#0e8f99` | `#62d4dc` |
| `--paper` (canvas) | `#fbfcfc` + teal 7% grid | `#0a0c0e` + cyan 4.5% grid |
| `--c-wall` / `--c-door` / `--c-window` | `#0e9aa5` `#d98a00` `#5468d4` | `#62d4dc` `#f0b24a` `#9db1ff` |
| Drawing panel (`.dpanel`) | `#0a0c0e` + 20px cyan grid, corner ticks — both themes | |

Type: Inter Tight (UI, 600 headlines at −0.035em), Space Mono (10.5px uppercase labels, +0.09em).
Scale: 34 / 28 / 20 / 15 / 14 / 13 / 12. Radii 6 controls · 9 buttons · 12–14 cards · 16 dialogs.
Motion 120–180ms UI, 280ms camera moves, outlines draw in with a 6ms stagger; `prefers-reduced-motion` respected.

## Key components
* **Check screen**: full-bleed canvas, floating tool pill (Select V · Wall W · Door O · Window N · Pan H ·
  Find more with AI), spotlight + auto-zoom on the current suggestion, review card with crop, Keep (K) /
  Not a … (D) / change type, layer list, filmstrip with status dots, totals strip, autosave chip, "?" shortcuts.
* **Next-up hero** (home): dark panel, one action, progress, live drawing with the plan set's labels.
* **Train**: class tiles with real example counts, speed cards with measured-rate estimates and cost,
  improvement history from registered versions, dark readiness checklist; advanced dialog for architecture,
  starting point (with license badges) and validated settings.
* **Training live**: test sheet with scan line (no fake detections), round ticker, per-round check-sheet metric,
  step list with real timings. **Results**: stamp, two-tone verdict, found/missed drawing, per-item cards vs the
  previous version, advice, engineer footer.
* Registry / Experiments / Deployments / API keys / API docs / Billing / Team use `regcard` + `rtable`.
