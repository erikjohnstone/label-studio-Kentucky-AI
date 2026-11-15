# Canonical Dataset Schema (v1.0)

CV and graph annotations share one identity model so they never become separate silos.

## Entities (all carry `organization_id`, `created_at`, `updated_at`)

| Entity | Key fields |
|---|---|
| Dataset | name, LS `project_id`, `allow_ka_model_training` (+ timestamped `consent_record`) |
| Taxonomy | dataset, `version`, `frozen`, `classes[]` = `{name, kind: cv\|node\|edge, color, aliases[], trade}` |
| SourceDocument | dataset, filename, `sha256`, `kind` (pdf_vector, pdf_raster, image, dxf), `storage_key`, `split_group` (building / project) |
| Sheet | document, `page_index`, `width/height` (render px), `rotation`, `source_units` (pt, cad_units, px), `source_to_image` (3×3 affine), `has_vector`, `vector_provenance`, `image_key`, `tiles_key`, `primitives_key`, LS `task` |
| Primitive (JSON per sheet) | `id`, `type` (line, curve, arc, polyline, rect, circle, text), `pts` (source coords), `pts_px`, `bbox` (px), `width`, `color`, `layer`, `linetype`, `handle`, `block`, `text`, `closed`, `provenance` (import, raster_inferred, ocr) |
| CanonicalObject | dataset, sheet, `uid`, `label`, `geometry_type`, `geometry` `{polygon, bbox, mask_rle_ls, point}` (image px), `primitive_ids[]`, `provenance`, `proposal_id`, `review_status`, `reviewed_by/at`, `annotator`, `ls_annotation_id/ls_result_id`, `is_negative`, `history[]`, `schema_version` |
| SheetGraph | sheet, `version`, `is_current`, `graph`, `stats`, `source`, `parent`, `review_status`, `message`, `created_by` (append-only versions) |
| Proposal | dataset, sheet, `kind`, `agent`, `agent_version`, `model_version`, `confidence`, `payload` (original, never mutated), `evidence`, `explanation`, `status`, `final_payload`, `reviewed_by/at`, `ls_prediction_id` |
| DatasetVersion | immutable `manifest` (sheets, approved objects, approved graph versions), frozen `taxonomy`, `splits` (+groups, strategy, seed), `readiness`, `content_hash` |

## Graph JSON

```json
{"schema_version": "1.0", "feature_spec": "ka-graph-features-1", "builder_params": {...},
 "nodes": [{"id": "p12", "type": "line", "label": "wall", "primitive_ids": ["p12"], "object_uid": "obj_ab12",
            "bbox": [x0,y0,x1,y1], "features": [17 floats], "layer": "A-WALL", "text": null,
            "provenance": "human|agent_accepted|geometric|import|raster_inferred", "review": "approved|pending|rejected",
            "confidence": null, "proposal_id": 33}],
 "edges": [{"id": "e4", "source": "p12", "target": "p13", "type": "connects_to|intersects|parallel_near|near",
            "label": "same_object|connects_to|hosted_by|bounded_by|contained_in|labels|none|null", "directed": false,
            "features": [9 floats], "provenance": "geometric|human|agent_accepted", "review": "pending|approved"}],
 "graph_labels": {}, "objects": {}}
```

* `type` = **geometric candidate** (how the builder found it). `label` = **semantic relation** (set by a
  person or an accepted proposal). A candidate edge is never treated as a verified relationship.
* Node/edge features are defined by `graph.builder.FEATURE_SPEC` (versioned); training export and
  inference use the same function.
* Hierarchy: primitive nodes → `object_uid` groups (semantic objects) → optional semantic nodes that
  reference primitives with `contained_in` edges. Cross-sheet relations (`same_object_across_sheets`)
  are reserved for a future `objects` registry and are never fabricated.

## Ground-truth rules
* CV: only `review_status = approved` objects (not negative) enter a version.
* Graph: only graphs with `review_status = approved`; inside them, an element is a training target only
  if `provenance = human` or `review = approved` (`datasets.quality.is_verified`). Everything else gets
  target `-1` and is ignored by the loss.
* Agent / model output is `Proposal` until accepted; accepted CV objects still start `pending` review.
* Editing an object in LS after review resets it to `pending`, with the previous state in `history`.

## Coordinate spaces
See `kentucky/coords.py`. Each sheet stores `source_to_image`; LS stores percentages; training uses
`image × training_scale`; predictions are mapped back to image px and to source (PDF points in the
unrotated page frame, or CAD model units). Round-trip and render-alignment tests:
`kentucky/tests/test_coords_ingest.py`.

## Versioning
`SCHEMA_VERSION` is stored on objects and graphs; taxonomies are versioned and frozen once used by a
dataset version; dataset versions are immutable and hashed (`content_hash`).
