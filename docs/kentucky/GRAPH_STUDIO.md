# Graph Studio — GNN labeling on vector blueprints

Open from **Dataset Center → Sheets → Graph Studio** (`/ka/graph/<sheet_id>/`).

## How the graph is built
`graph/builder.py` turns every extracted primitive into a node and proposes **candidate** edges:

| Candidate type | Rule (tolerances scale with sheet diagonal) |
|---|---|
| `connects_to` | endpoints within 0.25 % of the diagonal (perpendicular flag in edge features) |
| `intersects` | geometries cross |
| `parallel_near` | lines within 3° and ≤ 1.8 % of the diagonal apart with > 50 % projected overlap (wall faces) |
| `near` | text → up to 3 nearest geometric primitives within 3 % (label association) |

Annotators correct and classify this structure instead of drawing every edge. Raster sheets use lines
vectorized with OpenCV LSD; they are drawn **dashed** and carry `provenance: raster_inferred` — never
presented as CAD geometry.

## Editing

| Action | How |
|---|---|
| Select primitive / node | click; shift-click adds; alt-click selects the whole object |
| Pan / zoom | drag / mouse wheel; **Fit** resets |
| Assign node label | keys **1–9** or the class buttons |
| Group into semantic object | **g** (also labels internal candidate edges `same_object`) |
| Ungroup | **u** |
| Add relation / edge | select exactly two nodes → choose relation (`hosted_by`, `bounded_by`, …) |
| Change / remove edge | inspector edge list: relation dropdown, × removes |
| Add semantic node | “Add semantic node” over selected primitives (`contained_in` edges) |
| Remove incorrect nodes | **Del** (removes from the graph only; source geometry is untouched) |
| Bulk | group edges → `same_object`; unlabeled edges → `none`; unlabeled nodes → `other` |
| Proposals | “Run geometry agent”, then accept ≥ confidence, accept/reject individually |
| Compare with a model | pick a node-classification model; mismatches turn red with an agreement score |
| Save | **Ctrl/⌘-S** → new immutable version (optimistic concurrency: 409 if someone saved meanwhile) |
| Review | Approve / Reject graph. Approval is refused while validation errors exist. |

Selecting a node highlights its source geometry; clicking an object in the **object-graph view**
(bottom-right, geometry-anchored layout of labeled objects and their relations) selects its primitives.
Overlay shows candidate edges for the selection, all labeled relations, or all candidates.

## Validation (`graph.builder.validate_graph`)
Errors: dangling edges, self loops, duplicate node ids, unknown node/edge labels, `same_object` edges
between nodes grouped into different objects. Warnings: duplicate edges, objects with mixed labels,
`same_object` endpoints with different labels, > 25 % isolated nodes. Info: unlabeled nodes.

## Provenance in the graph
Human edits set `provenance: human`, `review: approved`. Accepted agent proposals set
`provenance: agent_accepted` and record `proposal_id`. Builder candidates stay `geometric` / `pending`.
Only verified elements become PyG targets.

## Export
Approved graphs export to `graphs/<sheet>.json` and to PyTorch Geometric `Data` objects
(`x`, `edge_index` (undirected edges both ways), `edge_attr`, `y`, `edge_y`, `edge_type`, `node_ids`).
