# Research index

All research used public, official sources; no accounts were created and no services were connected.

| Topic | Document |
|---|---|
| Fireworks AI training, registry, deployments, keys, billing — and which patterns we adopt | [FIREWORKS_RESEARCH.md](FIREWORKS_RESEARCH.md) |
| Roboflow, AutoTrain, CVAT, Label Studio ML backend, Modal, Lambda, PyTorch Geometric, FloorPlanCAD, licenses | [research/ML_PLATFORM_RESEARCH.md](research/ML_PLATFORM_RESEARCH.md) |
| What we reuse from Label Studio (and the Community/Enterprise boundary) | [LABEL_STUDIO_AUDIT.md](LABEL_STUDIO_AUDIT.md) |
| Model and checkpoint licenses | [LICENSING.md](LICENSING.md), [MODEL_CATALOG.md](MODEL_CATALOG.md) |
| GPU providers, terms of service, spending safety | [GPU_PROVIDERS.md](GPU_PROVIDERS.md) |
| Task-specific pretrained base models and their code / weights / data licenses | [research/BASE_MODELS.md](research/BASE_MODELS.md) |
| UI/UX: seven research passes and the resulting design system | [DESIGN_TOKENS.md](DESIGN_TOKENS.md) (below) and `design/concepts/` |

## UI/UX research (seven parallel studies, real 1440×900 captures)

1. **Apple Design Award apps** (Copilot, Flighty, Halide, Things): "you just approve" flows, status as
   sentences, honest progress, a moment of celebration when work completes.
2. **AI/ML training products** (Ultralytics HUB, LandingLens, Roboflow, Teachable Machine, Create ML):
   cost before training, guided readiness checklists, metric tiles with history, two-pane try-it,
   AI suggestions shown dashed with an accept threshold.
3. **Design galleries** (Godly, Dribbble industrial/blueprint, US Graphics, Anduril, Teenage Engineering):
   graphite + one cyan accent, one display element per screen, title-block framing, hairlines over cards.
4. **Canvas and annotation tools** (tldraw, Excalidraw, Figma UI3, Encord, SuperAnnotate, CVAT, V7, Bluebeam):
   full-bleed canvas, floating labelled tool pill with shortcut letters, review queue with Keep/Dismiss and
   auto-zoom, filmstrip with status dots, autosave chip, "?" shortcut sheet.
5. **Awwwards winners** (Linear, Raycast, Resend, Evervault, Basement, Modal, Warp): tight display type,
   two-tone headlines, mono instrument labels, "+" tick rules, live status grids, restrained motion.
6. **Best-in-class SaaS** (Linear, Vercel Geist, Raycast, Supabase, Railway, Clerk, Stripe): white-alpha
   elevation, 1px hairline borders, four text tiers, dense 13px UI type, empty states with one action.
7. **Construction tech** (Kreo, PlanSwift, Togal.AI, Beam AI, STACK, Bluebeam, Procore, Handoff,
   Document Crunch): dim the sheet and light up detections, show the AI working (scan sweep), labels and
   counts on the drawing, legend as layer control, confidence triage, totals strip, outcome copy.

Decisions taken from it are recorded in [DESIGN_TOKENS.md](DESIGN_TOKENS.md). Screenshots were working
material in the session scratchpad and are not committed (third-party imagery).
