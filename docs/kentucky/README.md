# Kentucky AI — construction model training platform

Start here: **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** (what works, what is blocked, how to run it)
and **[TEST_RESULTS.md](TEST_RESULTS.md)** (what was measured).

## Using the platform (contractor workflow)
1. **Plan sets** (`/ka/`): drop PDFs, DXF or scans. Each page becomes a sheet; vector lines, text (OCR for
   scans) and tiles are extracted, with exact source↔image coordinates.
2. **Check** (`/ka/markup/<sheet>/`): press **Find more with AI**. Your best trained model marks up the sheet
   (or, before you have one, the geometry agent reads the drawing's lines). Each suggestion is zoomed and
   highlighted: **K** keep, **D** dismiss, **W/O/N** change type. Draw anything missed with Wall/Door/Window
   (drag a box). Everything autosaves. **Done · Next sheet** approves the sheet for training.
   Precise polygon work: "Precise outline editor" (embedded Label Studio engine).
3. **Graph Studio** (`/ka/graph/<sheet>/`): label vector lines for graph models — select primitives, group
   them into objects, fix edges, approve and version the graph.
4. **Train** (`/ka/train/?dataset=<id>`): shows what the model will learn (real example counts), how long and
   what it costs, and a readiness checklist. **Customize model & settings** picks the task, architecture,
   starting point (with license status) and validated hyperparameters.
5. **Training** (`/ka/runs/<job>/`): real progress, per-round check-sheet score, step timings, Stop.
   When it finishes the same page shows **Results**: what it found and missed on a sheet it never saw,
   per-item scores against the previous version, and advice.
6. **Deploy** ("Use this model"), create an **API key**, and call the endpoint — see **API docs** in the app.
7. **Experiments** compares runs; **Models** keeps every version with lineage; **Billing** sets the monthly
   limit; **Team** controls whether Kentucky AI may learn from a plan set (off by default).

## Reference
| | |
|---|---|
| Architecture | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Label Studio reuse | [LABEL_STUDIO_AUDIT.md](LABEL_STUDIO_AUDIT.md) |
| Canonical schema | [DATASET_SCHEMA.md](DATASET_SCHEMA.md) |
| Graph Studio | [GRAPH_STUDIO.md](GRAPH_STUDIO.md) |
| Models and licenses | [MODEL_CATALOG.md](MODEL_CATALOG.md), [LICENSING.md](LICENSING.md) |
| Training | [TRAINING.md](TRAINING.md) |
| GPUs | [GPU_PROVIDERS.md](GPU_PROVIDERS.md) |
| Deployment and API | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Billing | [BILLING.md](BILLING.md) |
| Security | [SECURITY.md](SECURITY.md) |
| Research | [RESEARCH.md](RESEARCH.md), [FIREWORKS_RESEARCH.md](FIREWORKS_RESEARCH.md) |
| Design | [DESIGN_TOKENS.md](DESIGN_TOKENS.md), `design/concepts/` |

## Known limitations
* No Kentucky AI pretrained checkpoints exist yet; the catalog says so.
* Paid GPUs (Modal/Lambda), Stripe, S3/R2 storage and hosted deployment are not connected (by instruction);
  see the credentials table in IMPLEMENTATION_STATUS.md.
* Accuracy numbers in this repo come from synthetic drawings; measure on real customer plans before relying on them.
* Drawing tools on the Check screen create boxes; arbitrary polygons use the precise editor.
