"""Kentucky AI REST API (``/api/ka/...``). Every endpoint is organization-scoped."""

from __future__ import annotations

import time
from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import catalog, storage
from .agent import labeling_assistant as LA
from .agent import training_advisor as TA
from .billing import ledger, pricing
from .datasets.quality import readiness
from .datasets.versioning import create_version
from .graph.builder import FEATURE_SPEC, build_graph, graph_stats, validate_graph
from .ingest.pipeline import IngestError, create_document, load_primitives, process_document
from .labeling import current_taxonomy, ensure_project, sync_from_label_studio
from .models import (
    ApiKey,
    AuditLog,
    CanonicalObject,
    Dataset,
    DatasetVersion,
    Deployment,
    LedgerEntry,
    ModelVersion,
    Proposal,
    Provenance,
    RegisteredModel,
    Review,
    Sheet,
    SheetGraph,
    SourceDocument,
    Taxonomy,
    TrainingJob,
)
from .orchestration import service as orch
from .orchestration.providers.base import paid_compute_enabled
from .security import ApiKeyAuthentication, audit, org_of, rate_limiter


def _get(klass, request, **f):
    obj = klass.objects.filter(organization=org_of(request), **f).first()
    if obj is None:
        raise NotFound()
    return obj


def _ser_dataset(d: Dataset):
    tax = current_taxonomy(d)
    return {'id': d.id, 'name': d.name, 'description': d.description, 'created_at': d.created_at, 'project_id': d.project_id,
            'documents': d.documents.count(), 'sheets': d.sheets.count(), 'versions': d.versions.count(),
            'objects': d.canonical_objects.filter(deleted=False).count(),
            'approved': d.canonical_objects.filter(deleted=False, review_status='approved').count(),
            'taxonomy_version': tax.version if tax else None, 'allow_ka_model_training': d.allow_ka_model_training,
            'labeled_sheets': d.sheets.exclude(labeling_status='unlabeled').count(),
            'cover': (lambda s0: f'/ka/files/sheet/{s0.id}/image.png' if s0 else None)(d.sheets.order_by('id').first())}


def _ser_sheet(s: Sheet):
    return {'id': s.id, 'name': s.name, 'dataset_id': s.dataset_id, 'document_id': s.document_id, 'page_index': s.page_index, 'width': s.width, 'height': s.height,
            'rotation': s.rotation, 'source_units': s.source_units, 'source_to_image': s.source_to_image, 'has_vector': s.has_vector,
            'vector_provenance': s.vector_provenance, 'primitive_count': s.primitive_count, 'text_count': s.text_count,
            'ocr_status': s.ocr_status, 'labeling_status': s.labeling_status, 'ls_task_id': s.ls_task_id,
            'image_url': f'/ka/files/sheet/{s.id}/image.png', 'tile_levels': s.tile_levels,
            'split_group': s.document.split_group, 'document_kind': s.document.kind,
            'objects': s.canonical_objects.filter(deleted=False).count(),
            'graph_version': (SheetGraph.objects.filter(sheet=s, is_current=True).values_list('version', flat=True).first())}


def _ser_job(j: TrainingJob, full=False):
    d = {'id': j.id, 'name': j.name, 'task': j.task, 'catalog_id': j.catalog_id, 'init': j.init, 'status': j.status,
         'dataset_id': j.dataset_version.dataset_id, 'dataset_version': j.dataset_version.version, 'dataset_version_id': j.dataset_version_id,
         'provider': j.provider, 'gpu_type': j.gpu_type, 'estimate': j.estimate, 'max_cost_usd': str(j.max_cost_usd),
         'created_at': j.created_at, 'started_at': j.started_at, 'finished_at': j.finished_at, 'error': j.error[:2000],
         'headline': (j.final_metrics or {}).get('headline'), 'cancel_requested': j.cancel_requested, 'attempt': j.attempt,
         'authorized_at': j.authorized_at, 'heartbeat_at': j.heartbeat_at, 'runtime_s': (j.resource_usage or {}).get('runtime_s'),
         'base_model_version': j.base_model_version_id,
         'model_version': j.model_versions.values_list('id', flat=True).first(),
         'report': TA.report_card(j.final_metrics, j.task) if j.status == 'COMPLETED' else None,
         'architecture': (catalog.get(j.catalog_id) or {}).get('plain_name') or j.catalog_id, 'architecture_tech': (catalog.get(j.catalog_id) or {}).get('name', j.catalog_id), 'dataset_name': j.dataset_version.dataset.name,
         'base_version': j.base_model_version.version if j.base_model_version_id else None,
         'deployed': Deployment.objects.filter(active_version__training_job=j, status='active').exists()}
    if full:
        sp = j.dataset_version.splits
        d.update({'eval_sheets': (sp.get('test') or []) + (sp.get('val') or []), 'config': j.config, 'seed': j.seed, 'code_version': j.code_version, 'status_history': j.status_history,
                  'metrics_history': j.metrics_history, 'final_metrics': j.final_metrics, 'resource_usage': j.resource_usage,
                  'provider_job_id': j.provider_job_id})
    return d


def _ser_mv(mv: ModelVersion, full=False):
    d = {'id': mv.id, 'model_id': mv.model_id, 'model_name': mv.model.name, 'version': mv.version, 'task': mv.model.task,
         'catalog_id': mv.model.catalog_id, 'created_at': mv.created_at, 'status': mv.status, 'training_job': mv.training_job_id,
         'dataset_version': mv.dataset_version.version if mv.dataset_version_id else None,
         'dataset_id': mv.dataset_version.dataset_id if mv.dataset_version_id else None,
         'headline': (mv.metrics or {}).get('headline'), 'license': mv.license, 'sha256': mv.artifact_sha256,
         'downloadable': mv.downloadable, 'classes': list(mv.label_map.values()),
         'report': TA.report_card(mv.metrics, mv.model.task),
         'architecture': (catalog.get(mv.model.catalog_id) or {}).get('plain_name') or mv.model.catalog_id, 'architecture_tech': (catalog.get(mv.model.catalog_id) or {}).get('name', mv.model.catalog_id),
         'init': mv.training_job.init if mv.training_job_id else None,
         'base_version': (mv.training_job.base_model_version.version if mv.training_job_id and mv.training_job.base_model_version_id else None),
         'dataset_name': mv.dataset_version.dataset.name if mv.dataset_version_id else None,
         'runtime_s': (mv.training_job.resource_usage or {}).get('runtime_s') if mv.training_job_id else None}
    if full:
        d.update({'metrics': mv.metrics, 'input_schema': mv.input_schema, 'output_schema': mv.output_schema})
    return d


def _ser_dep(d: Deployment):
    return {'id': d.id, 'name': d.name, 'slug': d.slug, 'model_id': d.model_id, 'model_name': d.model.name, 'task': d.model.task,
            'active_version': d.active_version_id, 'active_version_number': d.active_version.version, 'status': d.status,
            'kind': d.kind, 'rate_limit_per_minute': d.rate_limit_per_minute, 'history': d.history, 'request_count': d.request_count,
            'error_count': d.error_count, 'last_request_at': d.last_request_at, 'created_at': d.created_at,
            'hosting_per_hour': pricing.pricing()['dedicated_hosting_per_hour'] if d.kind == 'dedicated' else None,
            'endpoint': f'/api/ka/v1/deployments/{d.slug}/predict'}


# =============================================================================== datasets
@api_view(['GET', 'POST'])
def datasets(request):
    org = org_of(request)
    if request.method == 'GET':
        return Response([_ser_dataset(d) for d in Dataset.objects.filter(organization=org, archived=False).order_by('-id')])
    name = (request.data.get('name') or '').strip()
    if not name:
        raise ValidationError({'name': 'required'})
    from .labeling import default_taxonomy_classes

    with transaction.atomic():
        d = Dataset.objects.create(organization=org, name=name[:200], description=request.data.get('description', ''), created_by=request.user,
                                   allow_ka_model_training=bool(request.data.get('allow_ka_model_training', False)))
        if d.allow_ka_model_training:
            d.consent_record = {'granted_by': request.user.id, 'at': timezone.now().isoformat(), 'text': 'Customer permits Kentucky AI to use this dataset to train Kentucky AI models.'}
            d.save(update_fields=['consent_record'])
        Taxonomy.objects.create(organization=org, dataset=d, version=1, classes=default_taxonomy_classes(request.data.get('classes')))
        ensure_project(d, request.user)
    audit(request, 'dataset.create', d)
    return Response(_ser_dataset(d), status=201)


@api_view(['GET', 'PATCH', 'DELETE'])
def dataset_detail(request, pk):
    d = _get(Dataset, request, pk=pk)
    if request.method == 'PATCH':
        for f in ('name', 'description'):
            if f in request.data:
                setattr(d, f, request.data[f])
        if 'allow_ka_model_training' in request.data:
            d.allow_ka_model_training = bool(request.data['allow_ka_model_training'])
            d.consent_record = {'granted' if d.allow_ka_model_training else 'revoked': True, 'by': request.user.id,
                                'at': timezone.now().isoformat(), 'previous': d.consent_record}
        d.save()
        audit(request, 'dataset.update', d, fields=list(request.data.keys()))
    if request.method == 'DELETE':
        # customer data deletion: originals, derived assets, annotations (LS project) and exports
        storage.delete_prefix(storage.key(d.organization_id, 'datasets', d.id), d.organization_id)
        if d.project_id:
            d.project.delete()
        audit(request, 'dataset.delete', d, name=d.name)
        d.delete()
        return Response(status=204)
    out = _ser_dataset(d)
    tax = current_taxonomy(d)
    out['taxonomy'] = tax.classes
    out['consent_record'] = d.consent_record
    out['label_studio_url'] = f'/projects/{d.project_id}/data' if d.project_id else None
    return Response(out)


@api_view(['GET', 'POST'])
def taxonomy(request, pk):
    d = _get(Dataset, request, pk=pk)
    tax = current_taxonomy(d)
    if request.method == 'POST':
        classes = request.data.get('classes')
        if not isinstance(classes, list) or not all(isinstance(c, dict) and c.get('name') and c.get('kind') in ('cv', 'node', 'edge') for c in classes):
            raise ValidationError({'classes': 'list of {name, kind: cv|node|edge, color?, aliases?, trade?}'})
        names = [(c['kind'], c['name']) for c in classes]
        if len(names) != len(set(names)):
            raise ValidationError({'classes': 'duplicate class names'})
        tax = Taxonomy.objects.create(organization=d.organization, dataset=d, version=tax.version + 1, classes=classes)
        ensure_project(d)
        audit(request, 'taxonomy.version', tax, version=tax.version)
    return Response({'version': tax.version, 'frozen': tax.frozen, 'classes': tax.classes,
                     'history': list(d.taxonomies.values('version', 'frozen', 'created_at'))})


@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def documents(request, pk):
    d = _get(Dataset, request, pk=pk)
    if request.method == 'GET':
        return Response([{'id': x.id, 'filename': x.filename, 'kind': x.kind, 'status': x.status, 'error': x.error, 'size_bytes': x.size_bytes,
                          'split_group': x.split_group, 'sheets': x.sheets.count(), 'created_at': x.created_at, 'sha256': x.sha256}
                         for x in d.documents.order_by('-id')])
    files = request.FILES.getlist('file')
    if not files:
        raise ValidationError({'file': 'upload one or more files'})
    out = []
    for f in files:
        try:
            data = f.read()
            doc = create_document(d, f.name, data, request.user, request.data.get('split_group', ''))
        except IngestError as e:
            out.append({'filename': f.name, 'status': 'rejected', 'error': str(e)})
            continue
        try:
            sheets = process_document(doc)
            out.append({'id': doc.id, 'filename': doc.filename, 'status': 'ready', 'kind': doc.kind, 'sheets': [s.id for s in sheets]})
        except Exception as e:  # noqa: BLE001
            out.append({'id': doc.id, 'filename': doc.filename, 'status': 'failed', 'error': str(e)[:500]})
        audit(request, 'document.upload', doc, filename=doc.filename, sha256=doc.sha256)
    return Response(out, status=201)


@api_view(['GET'])
def sheets(request, pk):
    d = _get(Dataset, request, pk=pk)
    return Response([_ser_sheet(s) for s in d.sheets.select_related('document').order_by('id')])


@api_view(['GET'])
def sheet_detail(request, pk):
    s = _get(Sheet, request, pk=pk)
    return Response(_ser_sheet(s))


@api_view(['GET'])
def sheet_primitives(request, pk):
    s = _get(Sheet, request, pk=pk)
    p = load_primitives(s)
    return Response({'primitives': p.get('primitives', []), 'vector_provenance': p.get('vector_provenance'),
                     'source_to_image': s.source_to_image, 'image_size': [s.width, s.height], 'metadata': p.get('metadata')})


@api_view(['GET', 'POST'])
def sheet_graph(request, pk):
    s = _get(Sheet, request, pk=pk)
    tax = current_taxonomy(s.dataset)
    if request.method == 'GET':
        g = LA.current_graph(s)
        return Response({'id': g.id, 'version': g.version, 'graph': g.graph, 'stats': g.stats, 'review_status': g.review_status,
                         'source': g.source, 'message': g.message, 'node_classes': tax.names('node'), 'edge_classes': tax.names('edge'),
                         'issues': validate_graph(g.graph, tax.names('node'), tax.names('edge'))})
    data = request.data.get('graph')
    base_version = request.data.get('base_version')
    if not isinstance(data, dict) or 'nodes' not in data or 'edges' not in data:
        raise ValidationError({'graph': 'nodes + edges required'})
    cur = LA.current_graph(s)
    if base_version is not None and int(base_version) != cur.version:
        return Response({'detail': f'Graph changed (current v{cur.version}); reload before saving'}, status=409)
    issues = validate_graph(data, tax.names('node'), tax.names('edge'))
    errors = [i for i in issues if i['severity'] == 'error']
    if errors and not request.data.get('allow_errors'):
        return Response({'detail': 'graph has validation errors', 'issues': errors}, status=400)
    # human edits: anything the client changed is human provenance (the client marks edited items)
    with transaction.atomic():
        g = LA.save_graph_version(s, data, request.user, source='human', message=request.data.get('message', ''), parent=cur)
    if s.labeling_status == 'unlabeled':
        s.labeling_status = 'in_progress'
        s.save(update_fields=['labeling_status'])
    audit(request, 'graph.save', g, sheet=s.id, version=g.version)
    return Response({'id': g.id, 'version': g.version, 'stats': g.stats, 'issues': issues}, status=201)


@api_view(['POST'])
def sheet_graph_review(request, pk):
    s = _get(Sheet, request, pk=pk)
    g = LA.current_graph(s)
    st = request.data.get('status')
    if st not in (Review.APPROVED, Review.REJECTED, Review.PENDING):
        raise ValidationError({'status': 'approved|rejected|pending'})
    tax = current_taxonomy(s.dataset)
    if st == Review.APPROVED:
        errs = [i for i in validate_graph(g.graph, tax.names('node'), tax.names('edge')) if i['severity'] == 'error']
        if errs:
            return Response({'detail': 'cannot approve a graph with validation errors', 'issues': errs}, status=400)
    g.review_status = st
    g.save(update_fields=['review_status'])
    if st == Review.APPROVED:
        s.labeling_status = 'reviewed'
        s.save(update_fields=['labeling_status'])
    audit(request, 'graph.review', g, status=st)
    return Response({'version': g.version, 'review_status': g.review_status})


@api_view(['GET'])
def sheet_graph_versions(request, pk):
    s = _get(Sheet, request, pk=pk)
    return Response([{'id': g.id, 'version': g.version, 'is_current': g.is_current, 'source': g.source, 'stats': g.stats,
                      'review_status': g.review_status, 'message': g.message, 'created_at': g.created_at,
                      'created_by': g.created_by.email if g.created_by_id else None} for g in s.graphs.all()[:50]])


@api_view(['POST'])
def sheet_graph_rebuild(request, pk):
    s = _get(Sheet, request, pk=pk)
    params = request.data.get('params') or {}
    gd = build_graph(load_primitives(s)['primitives'], (s.width, s.height), params)
    g = LA.save_graph_version(s, gd, request.user, source='builder', message=f'rebuilt candidate graph {params}')
    return Response({'version': g.version, 'stats': g.stats}, status=201)


@api_view(['POST'])
def dataset_sync(request, pk):
    d = _get(Dataset, request, pk=pk)
    return Response(sync_from_label_studio(d))


@api_view(['GET'])
def dataset_objects(request, pk):
    d = _get(Dataset, request, pk=pk)
    qs = CanonicalObject.objects.filter(dataset=d, deleted=False)
    if request.GET.get('status'):
        qs = qs.filter(review_status=request.GET['status'])
    if request.GET.get('sheet'):
        qs = qs.filter(sheet_id=request.GET['sheet'])
    return Response([{'id': o.id, 'uid': o.uid, 'sheet_id': o.sheet_id, 'label': o.label, 'geometry_type': o.geometry_type,
                      'geometry': {k: v for k, v in o.geometry.items() if k != 'mask_rle_ls'}, 'provenance': o.provenance,
                      'review_status': o.review_status, 'proposal_id': o.proposal_id, 'is_negative': o.is_negative,
                      'annotator': o.annotator.email if o.annotator_id else None, 'history': o.history[-5:]}
                     for o in qs.select_related('annotator').order_by('sheet_id', 'id')[:2000]])


@api_view(['POST'])
def objects_review(request, pk):
    d = _get(Dataset, request, pk=pk)
    ids = request.data.get('ids') or []
    st = request.data.get('status')
    if st not in (Review.APPROVED, Review.REJECTED, Review.PENDING):
        raise ValidationError({'status': 'approved|rejected|pending'})
    qs = CanonicalObject.objects.filter(dataset=d, id__in=ids)
    n = 0
    for o in qs:
        o.history.append({'at': timezone.now().isoformat(), 'by': request.user.id, 'action': f'review:{st}', 'before': o.review_status,
                          'comment': request.data.get('comment', '')[:500]})
        o.review_status, o.reviewed_by, o.reviewed_at = st, request.user, timezone.now()
        o.save()
        n += 1
    audit(request, 'objects.review', d, status=st, count=n)
    return Response({'updated': n})


@api_view(['GET'])
def dataset_readiness(request, pk):
    d = _get(Dataset, request, pk=pk)
    return Response(readiness(d, current_taxonomy(d)))


@api_view(['GET', 'POST'])
def dataset_versions(request, pk):
    d = _get(Dataset, request, pk=pk)
    if request.method == 'POST':
        v = create_version(d, request.user, seed=int(request.data.get('seed', 0)), strategy=request.data.get('strategy', 'group'),
                           notes=request.data.get('notes', ''))
        audit(request, 'dataset.version', v, version=v.version, content_hash=v.content_hash)
        return Response(_ser_version(v), status=201)
    return Response([_ser_version(v) for v in d.versions.all()])


def _ser_version(v):
    return {'id': v.id, 'dataset_id': v.dataset_id, 'version': v.version, 'created_at': v.created_at, 'content_hash': v.content_hash,
            'readiness': v.readiness, 'splits': {k: v.splits[k] for k in ('train', 'val', 'test')}, 'split_groups': v.splits.get('groups'),
            'strategy': v.splits.get('strategy'), 'objects': len(v.manifest['objects']), 'graphs': len(v.manifest['graphs']),
            'taxonomy_version': v.taxonomy.get('version'), 'export_formats': v.export_formats, 'notes': v.notes}


@api_view(['POST'])
def version_export(request, pk):
    from pathlib import Path
    import tempfile

    from .datasets.export import export_version, store_export

    v = _get(DatasetVersion, request, pk=pk)
    if not v.export_key or not storage.exists(v.export_key):
        with tempfile.TemporaryDirectory() as td:
            out = export_version(v, Path(td) / 'bundle')
            store_export(v, out)
    audit(request, 'dataset.export', v)
    return Response({'url': storage.signed_url(v.export_key, v.organization_id, filename=f'dataset{v.dataset_id}_v{v.version}.zip'),
                     'formats': v.export_formats, 'expires_in_s': storage.DEFAULT_TTL_S})


# =============================================================================== agent
@api_view(['POST'])
def agent_action(request, pk, action):
    d = _get(Dataset, request, pk=pk)
    sheet = None
    if request.data.get('sheet_id') is not None:
        sheet = _get(Sheet, request, pk=request.data['sheet_id'], dataset=d)
    if action == 'suggest-classes':
        props = LA.suggest_classes(d)
    elif action == 'propose-graph':
        if sheet is None:
            raise ValidationError({'sheet_id': 'required'})
        _, props = LA.propose_graph(sheet, d)
    elif action == 'propose-cv':
        if sheet is None:
            raise ValidationError({'sheet_id': 'required'})
        props = LA.propose_cv_from_graph(sheet, d)
    elif action == 'propose-from-model':
        if sheet is None:
            raise ValidationError({'sheet_id': 'required'})
        mv = _get(ModelVersion, request, pk=request.data.get('model_version_id'))
        props = LA.propose_from_model(sheet, d, mv)
    elif action == 'quality-review':
        props = LA.quality_review(d)
    elif action == 'summary':
        return Response(LA.dataset_summary(d))
    else:
        raise NotFound()
    audit(request, f'agent.{action}', d, proposals=len(props))
    return Response({'created': len(props), 'agent': f'{LA.AGENT}@{LA.AGENT_VERSION}'}, status=201)


@api_view(['GET'])
def proposals(request, pk):
    d = _get(Dataset, request, pk=pk)
    qs = Proposal.objects.filter(dataset=d)
    for f in ('status', 'kind', 'agent'):
        if request.GET.get(f):
            qs = qs.filter(**{f: request.GET[f]})
    if request.GET.get('sheet'):
        qs = qs.filter(sheet_id=request.GET['sheet'])
    return Response([{'id': p.id, 'sheet_id': p.sheet_id, 'kind': p.kind, 'agent': p.agent, 'agent_version': p.agent_version,
                      'model_version': p.model_version_id, 'confidence': p.confidence, 'payload': p.payload, 'evidence': p.evidence,
                      'explanation': p.explanation, 'status': p.status, 'final_payload': p.final_payload, 'created_at': p.created_at,
                      'reviewed_by': p.reviewed_by.email if p.reviewed_by_id else None}
                     for p in qs.select_related('reviewed_by').order_by('-id')[:1000]])


@api_view(['POST'])
def proposal_review(request, pk):
    p = _get(Proposal, request, pk=pk)
    action = request.data.get('action')
    if p.status != Proposal.Status.PENDING:
        raise ValidationError({'detail': f'proposal already {p.status}'})
    now = timezone.now()
    if action == 'reject':
        p.status = Proposal.Status.REJECTED
    elif action in ('accept', 'modify'):
        final = request.data.get('final_payload') if action == 'modify' else None
        if p.kind in (Proposal.Kind.NODE_LABEL, Proposal.Kind.GROUP):
            if final:
                p._override = {**p.payload, **{k: v for k, v in final.items() if k in ('label', 'node_ids', 'group')}}
            LA.apply_graph_proposals(p.sheet, [p], request.user, accept=True)
            p.refresh_from_db()
            if final:
                p.status = Proposal.Status.MODIFIED
        elif p.kind == Proposal.Kind.CV_OBJECT:
            g = final or p.payload
            obj = CanonicalObject.objects.create(
                organization=p.organization, dataset=p.dataset, sheet=p.sheet, label=g['label'], geometry_type='polygon',
                geometry={'polygon': g['polygon']}, primitive_ids=g.get('primitive_ids', []), provenance=Provenance.AGENT_ACCEPTED,
                proposal=p, annotator=request.user, review_status=Review.PENDING,
                attributes={'accepted_from': f'{p.agent}@{p.agent_version}', 'modified': bool(final)})
            p.status = Proposal.Status.MODIFIED if final else Proposal.Status.ACCEPTED
            p.final_payload = {**g, 'object_uid': obj.uid}
        elif p.kind == Proposal.Kind.CLASS_SUGGESTION:
            d = p.dataset
            tax = current_taxonomy(d)
            if not tax.resolve(p.payload['class'], 'cv'):
                from .labeling import DEFAULT_CLASSES

                spec = next((c for c in DEFAULT_CLASSES if c[0] == p.payload['class'] and c[1] == 'cv'), None)
                cls = {'name': p.payload['class'], 'kind': 'cv', 'color': spec[2] if spec else '#62d4dc', 'trade': spec[3] if spec else 'any',
                       'aliases': spec[4] if spec else []}
                Taxonomy.objects.create(organization=d.organization, dataset=d, version=tax.version + 1, classes=tax.classes + [cls])
                ensure_project(d)
            p.status = Proposal.Status.ACCEPTED
        else:
            p.status = Proposal.Status.ACCEPTED if action == 'accept' else Proposal.Status.MODIFIED
        p.final_payload = p.final_payload or final
    elif action == 'dismiss':
        p.status = Proposal.Status.DISMISSED
    else:
        raise ValidationError({'action': 'accept|modify|reject|dismiss'})
    p.reviewed_by, p.reviewed_at = request.user, now
    p.save()
    audit(request, f'proposal.{action}', p)
    return Response({'id': p.id, 'status': p.status, 'final_payload': p.final_payload})


@api_view(['POST'])
def sheet_apply_proposals(request, pk):
    s = _get(Sheet, request, pk=pk)
    accept = request.data.get('accept', True)
    qs = Proposal.objects.filter(sheet=s, status='pending', kind__in=[Proposal.Kind.NODE_LABEL, Proposal.Kind.GROUP])
    if request.data.get('ids'):
        qs = qs.filter(id__in=request.data['ids'])
    minc = float(request.data.get('min_confidence', 0))
    props = [p for p in qs if (p.confidence or 0) >= minc]
    g = LA.apply_graph_proposals(s, props, request.user, accept=bool(accept))
    audit(request, 'proposals.apply', s, count=len(props), accept=bool(accept))
    return Response({'applied': len(props), 'graph_version': g.version})


# =============================================================================== catalog / training
@api_view(['GET'])
def model_catalog(request):
    org_of(request)
    return Response(catalog.public_catalog())


@api_view(['GET'])
def training_recommend(request):
    v = _get(DatasetVersion, request, pk=request.GET.get('dataset_version'))
    from .training.config import recommended

    mvs = ModelVersion.objects.filter(organization=v.organization, status='ready').select_related('model')
    rec = TA.recommend(v, list(mvs))
    rec['configs'] = {c['id']: recommended(c['id'], {'train_items': len(v.splits['train'])}) for c in catalog.CATALOG}
    for t in rec['tasks']:
        t['config'] = rec['configs'][t['catalog_id']]
        t['estimate'] = {g: pricing.estimate_training(t['catalog_id'], t['config'], len(v.splits['train']), g)
                         for g in ('cpu-local', 'nvidia-t4', 'nvidia-a10g')}
    return Response(rec)


@api_view(['GET', 'POST'])
def jobs(request):
    org = org_of(request)
    if request.method == 'GET':
        qs = TrainingJob.objects.filter(organization=org).select_related('dataset_version').order_by('-id')
        if request.GET.get('dataset'):
            qs = qs.filter(dataset_version__dataset_id=request.GET['dataset'])
        return Response([_ser_job(j) for j in qs[:200]])
    v = _get(DatasetVersion, request, pk=request.data.get('dataset_version_id'))
    base = None
    if request.data.get('base_model_version_id'):
        base = _get(ModelVersion, request, pk=request.data['base_model_version_id'])
    j = orch.create_job(org, request.user, v, request.data.get('catalog_id', ''), request.data.get('init', 'scratch'),
                        request.data.get('config') or {}, base, request.data.get('gpu_type', 'cpu-local'), request.data.get('name', ''))
    audit(request, 'training.create', j, status=j.status)
    return Response(_ser_job(j, full=True), status=201)


@api_view(['GET'])
def job_detail(request, pk):
    return Response(_ser_job(_get(TrainingJob, request, pk=pk), full=True))


@api_view(['POST'])
def job_authorize(request, pk):
    j = _get(TrainingJob, request, pk=pk)
    if not request.data.get('confirm'):
        raise ValidationError({'confirm': 'explicit confirmation required to authorize compute spend'})
    try:
        orch.authorize(j, request.user, request.data.get('max_cost_usd'))
    except orch.JobError as e:
        raise ValidationError({'detail': str(e)})
    audit(request, 'training.authorize', j, max_cost=str(j.max_cost_usd), provider=j.provider, gpu=j.gpu_type)
    return Response(_ser_job(j, full=True))


@api_view(['POST'])
def job_cancel(request, pk):
    j = _get(TrainingJob, request, pk=pk)
    orch.request_cancel(j)
    audit(request, 'training.cancel', j)
    return Response(_ser_job(j))


@api_view(['GET'])
def job_diagnose(request, pk):
    return Response(TA.diagnose(_get(TrainingJob, request, pk=pk)))


@api_view(['GET'])
def jobs_compare(request):
    ids = [int(x) for x in request.GET.get('ids', '').split(',') if x.strip().isdigit()]
    js = list(TrainingJob.objects.filter(organization=org_of(request), id__in=ids).select_related('dataset_version'))
    return Response(TA.compare(js))


# =============================================================================== registry / deployments
@api_view(['GET'])
def models_list(request):
    org = org_of(request)
    out = []
    for m in RegisteredModel.objects.filter(organization=org).order_by('-id'):
        out.append({'id': m.id, 'name': m.name, 'task': m.task, 'catalog_id': m.catalog_id, 'archived': m.archived,
                    'versions': [_ser_mv(v) for v in m.versions.select_related('dataset_version', 'model')]})
    return Response(out)


@api_view(['GET'])
def model_version_detail(request, pk):
    return Response(_ser_mv(_get(ModelVersion, request, pk=pk), full=True))


@api_view(['POST'])
def model_version_archive(request, pk):
    mv = _get(ModelVersion, request, pk=pk)
    if Deployment.objects.filter(active_version=mv, status='active').exists():
        raise ValidationError({'detail': 'version is serving an active deployment; roll back first'})
    mv.status = 'archived' if request.data.get('archive', True) else 'ready'
    mv.save(update_fields=['status'])
    audit(request, 'model.archive', mv, status=mv.status)
    return Response(_ser_mv(mv))


@api_view(['GET'])
def model_version_download(request, pk):
    mv = _get(ModelVersion, request, pk=pk)
    if not mv.downloadable:
        raise PermissionDenied('download not permitted for this model')
    audit(request, 'model.download', mv)
    return Response({'url': storage.signed_url(mv.artifact_key, mv.organization_id, filename=f'{mv.model.name}_v{mv.version}.pt'),
                     'sha256': mv.artifact_sha256, 'expires_in_s': storage.DEFAULT_TTL_S})


@api_view(['GET', 'POST'])
def deployments(request):
    org = org_of(request)
    if request.method == 'GET':
        return Response([_ser_dep(d) for d in Deployment.objects.filter(organization=org).exclude(status='deleted').select_related('model', 'active_version').order_by('-id')])
    mv = _get(ModelVersion, request, pk=request.data.get('model_version_id'))
    if mv.status != 'ready':
        raise ValidationError({'detail': 'model version is archived'})
    if not mv.license.get('commercially_deployable'):
        raise ValidationError({'detail': f'Not deployable: {mv.license.get("reason")}'})
    if not request.data.get('confirm'):
        raise ValidationError({'confirm': 'explicit confirmation required: deployment exposes an authenticated API endpoint'})
    name = request.data.get('name') or f'{mv.model.name}'
    kind = request.data.get('kind', 'serverless')
    if kind not in ('serverless', 'dedicated'):
        raise ValidationError({'kind': 'serverless | dedicated'})
    if kind == 'dedicated':
        ok, why = ledger.check_spend(org, Decimal(pricing.pricing()['dedicated_hosting_per_hour']))
        if not ok:
            raise ValidationError({'detail': f'Always-on hosting would pass your monthly limit: {why}'})
    slug = f'{slugify(name)[:50]}-{org.id}-{int(time.time()) % 100000}'
    d = Deployment.objects.create(organization=org, name=name[:200], slug=slug, model=mv.model, active_version=mv, created_by=request.user,
                                  kind=kind, hosting_billed_until=timezone.now() if kind == 'dedicated' else None,
                                  rate_limit_per_minute=int(request.data.get('rate_limit_per_minute', 60)),
                                  history=[{'version_id': mv.id, 'version': mv.version, 'at': timezone.now().isoformat(), 'by': request.user.id, 'action': 'create'}])
    audit(request, 'deployment.create', d, version=mv.id, kind=kind)
    if kind == 'dedicated':  # keep the weights loaded: first request is as fast as the rest
        from .inference.predictors import load_checkpoint

        load_checkpoint(mv)
    return Response(_ser_dep(d), status=201)


@api_view(['POST'])
def deployment_action(request, pk, action):
    d = _get(Deployment, request, pk=pk)
    now = timezone.now().isoformat()
    if action == 'set-version':
        mv = _get(ModelVersion, request, pk=request.data.get('model_version_id'), model=d.model)
        if not mv.license.get('commercially_deployable') or mv.status != 'ready':
            raise ValidationError({'detail': 'version not deployable'})
        d.history = d.history + [{'version_id': mv.id, 'version': mv.version, 'at': now, 'by': request.user.id, 'action': 'set-version',
                                  'previous': d.active_version_id}]
        d.active_version = mv
    elif action == 'rollback':
        prev = [h for h in d.history if h.get('version_id') != d.active_version_id]
        if not prev:
            raise ValidationError({'detail': 'no previous version to roll back to'})
        mv = _get(ModelVersion, request, pk=prev[-1]['version_id'])
        d.history = d.history + [{'version_id': mv.id, 'version': mv.version, 'at': now, 'by': request.user.id, 'action': 'rollback',
                                  'previous': d.active_version_id}]
        d.active_version = mv
    elif action in ('pause', 'resume', 'delete'):
        from .billing import hosting

        if action in ('pause', 'delete') and d.status == 'active':
            hosting.accrue(d, final=True)  # bill the hosted time up to now, pro-rata
        if action == 'resume' and d.kind == 'dedicated':
            d.hosting_billed_until = timezone.now()
        d.status = {'pause': 'paused', 'resume': 'active', 'delete': 'deleted'}[action]
    elif action == 'rate-limit':
        d.rate_limit_per_minute = max(1, min(int(request.data.get('rate_limit_per_minute', 60)), 6000))
    else:
        raise NotFound()
    d.save()
    audit(request, f'deployment.{action}', d)
    return Response(_ser_dep(d))


# =============================================================================== inference (API key)
@api_view(['POST'])
@authentication_classes([ApiKeyAuthentication])
@permission_classes([])
def predict(request, slug):
    key = getattr(request, 'ka_api_key', None)
    if key is None or 'inference' not in (key.scopes or []):
        return Response({'error': {'code': 'unauthorized', 'message': 'Bearer API key with inference scope required'}}, status=401)
    d = Deployment.objects.filter(slug=slug, organization=key.organization).select_related('active_version', 'model').first()
    if d is None or d.status == 'deleted':
        return Response({'error': {'code': 'not_found', 'message': 'deployment not found'}}, status=404)
    if d.status != 'active':
        return Response({'error': {'code': 'paused', 'message': 'deployment is paused'}}, status=409)
    if not rate_limiter.allow(f'dep:{d.id}', d.rate_limit_per_minute):
        return Response({'error': {'code': 'rate_limited', 'message': f'limit {d.rate_limit_per_minute}/min'}}, status=429,
                        headers={'Retry-After': '60'})
    from .inference.predictors import InferenceError
    from .inference.predictors import predict as run

    t0 = time.time()
    request_id = request.META.get('HTTP_IDEMPOTENCY_KEY') or f'{d.id}:{time.time_ns()}'
    try:
        result = run(d.active_version, request.data, key.organization_id)
    except InferenceError as e:
        Deployment.objects.filter(pk=d.pk).update(error_count=d.error_count + 1)
        return Response({'error': {'code': 'bad_request', 'message': str(e)}}, status=400)
    except Exception as e:  # noqa: BLE001
        Deployment.objects.filter(pk=d.pk).update(error_count=d.error_count + 1)
        return Response({'error': {'code': 'inference_failed', 'message': type(e).__name__}}, status=500)
    ms = round((time.time() - t0) * 1000, 1)
    infra, charge = pricing.inference_charge(d.model.task, 1)
    entry, created = ledger.record(key.organization, LedgerEntry.Kind.INFERENCE, f'inf:{d.id}:{request_id}', 1, 'request', infra, charge,
                                   'deployment', d.id, f'{d.name} v{d.active_version.version}')
    Deployment.objects.filter(pk=d.pk).update(request_count=d.request_count + 1, last_request_at=timezone.now())
    AuditLog.objects.create(organization=key.organization, api_key=key, action='inference.predict', target_type='Deployment',
                            target_id=str(d.id), data={'ms': ms, 'version': d.active_version_id, 'billed': created}, ip=request.META.get('REMOTE_ADDR', ''))
    return Response({**result, 'deployment': d.slug, 'model_version_number': d.active_version.version, 'latency_ms': ms,
                     'usage': {'requests': 1, 'charge_usd': str(entry.customer_charge_usd), 'duplicate_request': not created}})


# =============================================================================== keys / billing / org
@api_view(['GET', 'POST'])
def api_keys(request):
    org = org_of(request)
    if request.method == 'POST':
        scopes = request.data.get('scopes') or ['inference']
        if not set(scopes) <= {'inference'}:
            raise ValidationError({'scopes': 'supported: inference'})
        k, raw = ApiKey.generate(org, (request.data.get('name') or 'API key')[:200], request.user, scopes)
        audit(request, 'apikey.create', k, prefix=k.prefix)
        return Response({'id': k.id, 'name': k.name, 'prefix': k.prefix, 'key': raw, 'note': 'Shown once. Store it securely.'}, status=201)
    return Response([{'id': k.id, 'name': k.name, 'prefix': k.prefix, 'scopes': k.scopes, 'created_at': k.created_at,
                      'revoked_at': k.revoked_at, 'last_used_at': k.last_used_at, 'rotated_from': k.rotated_from_id}
                     for k in ApiKey.objects.filter(organization=org).order_by('-id')])


@api_view(['POST'])
def api_key_action(request, pk, action):
    k = _get(ApiKey, request, pk=pk)
    if k.revoked_at:
        raise ValidationError({'detail': 'key already revoked'})
    if action == 'revoke':
        k.revoked_at = timezone.now()
        k.save(update_fields=['revoked_at'])
        audit(request, 'apikey.revoke', k)
        return Response({'id': k.id, 'revoked_at': k.revoked_at})
    if action == 'rotate':
        with transaction.atomic():
            new, raw = ApiKey.generate(k.organization, k.name, request.user, k.scopes, rotated_from=k)
            k.revoked_at = timezone.now()
            k.save(update_fields=['revoked_at'])
        audit(request, 'apikey.rotate', new, old=k.id)
        return Response({'id': new.id, 'prefix': new.prefix, 'key': raw, 'revoked': k.id, 'note': 'Shown once.'}, status=201)
    raise NotFound()


@api_view(['GET', 'PATCH'])
def billing(request):
    org = org_of(request)
    acct = ledger.account(org)
    if request.method == 'PATCH':
        if 'monthly_spend_cap_usd' in request.data:
            v = Decimal(str(request.data['monthly_spend_cap_usd']))
            if v < 0 or v > Decimal('1000000'):
                raise ValidationError({'monthly_spend_cap_usd': 'out of range'})
            acct.monthly_spend_cap_usd = v
        if request.data.get('payment_method') == 'test_card':
            if ledger.stripe_mode() == 'live':
                raise ValidationError({'detail': 'test cards are not allowed in live mode'})
            if ledger.stripe_mode() == 'test':
                try:
                    ledger.ensure_stripe_customer(org, test_card=True)
                except Exception as e:  # noqa: BLE001
                    raise ValidationError({'detail': f'Stripe (test mode) refused: {e}'})
                acct.refresh_from_db()
            acct.payment_method_status = 'test_card'
        if request.data.get('payment_method') == 'remove':
            acct.payment_method_status = 'none'
        acct.save()
        audit(request, 'billing.update', acct, fields=list(request.data.keys()))
    entries = LedgerEntry.objects.filter(organization=org).order_by('-id')[:200]
    return Response({
        'account': {'payment_method_status': acct.payment_method_status, 'monthly_spend_cap_usd': str(acct.monthly_spend_cap_usd),
                    'prepaid_credit_usd': str(acct.prepaid_credit_usd), 'stripe_mode': ledger.stripe_mode(),
                    'stripe_customer': bool(acct.stripe_customer_id)},
        'usage': ledger.usage_summary(org), 'pricing': pricing.pricing(),
        'history': [{'id': e.id, 'kind': e.kind, 'quantity': str(e.quantity), 'unit': e.unit, 'infra_cost_usd': str(e.infra_cost_usd),
                     'customer_charge_usd': str(e.customer_charge_usd), 'description': e.description, 'reference': f'{e.reference_type}:{e.reference_id}',
                     'stripe_status': e.stripe_status, 'created_at': e.created_at, 'idempotency_key': e.idempotency_key} for e in entries],
    })


@api_view(['GET'])
def org_info(request):
    org = org_of(request)
    from organizations.models import OrganizationMember

    members = [{'id': m.user.id, 'email': m.user.email, 'is_owner': m.is_owner}
               for m in OrganizationMember.objects.filter(organization=org, deleted_at=None).select_related('user')]
    return Response({'id': org.id, 'title': org.title, 'members': members, 'user': {'id': request.user.id, 'email': request.user.email},
                     'storage': 'local filesystem (private, org-prefixed keys, signed download URLs)',
                     'paid_compute_enabled': paid_compute_enabled(), 'stripe_mode': ledger.stripe_mode(),
                     'feature_spec': FEATURE_SPEC['version']})


@api_view(['GET'])
def audit_log(request):
    org = org_of(request)
    return Response([{'id': a.id, 'action': a.action, 'actor': a.actor.email if a.actor_id else None, 'api_key': a.api_key.prefix if a.api_key_id else None,
                      'target': f'{a.target_type}:{a.target_id}', 'data': a.data, 'ip': a.ip, 'created_at': a.created_at}
                     for a in AuditLog.objects.filter(organization=org).select_related('actor', 'api_key').order_by('-id')[:300]])


@api_view(['GET'])
def dashboard(request):
    org = org_of(request)
    return Response({
        'datasets': Dataset.objects.filter(organization=org, archived=False).count(),
        'sheets': Sheet.objects.filter(organization=org).count(),
        'objects_approved': CanonicalObject.objects.filter(organization=org, deleted=False, review_status='approved').count(),
        'objects_pending': CanonicalObject.objects.filter(organization=org, deleted=False, review_status='pending').count(),
        'proposals_pending': Proposal.objects.filter(organization=org, status='pending').count(),
        'jobs_active': TrainingJob.objects.filter(organization=org, status__in=orch.ACTIVE + ['QUEUED']).count(),
        'jobs': [_ser_job(j) for j in TrainingJob.objects.filter(organization=org).select_related('dataset_version').order_by('-id')[:6]],
        'models': ModelVersion.objects.filter(organization=org, status='ready').count(),
        'deployments': Deployment.objects.filter(organization=org, status='active').count(),
        'usage': ledger.usage_summary(org),
        'documents_by_kind': {k: SourceDocument.objects.filter(organization=org, kind=k).count() for k in SourceDocument.Kind.values},
    })


@api_view(['POST'])
def model_version_predict(request, pk):
    """Internal (session) prediction for experiment review / prediction-vs-ground-truth comparison.
    Not metered: it serves the customer's own evaluation workflow, not production traffic."""
    from .inference.predictors import InferenceError
    from .inference.predictors import predict as run

    mv = _get(ModelVersion, request, pk=pk)
    try:
        return Response(run(mv, request.data, mv.organization_id))
    except InferenceError as e:
        raise ValidationError({'detail': str(e)})


# =============================================================================== contractor mark-up (embedded LS engine)
@api_view(['GET', 'POST'])
def sheet_markup(request, pk):
    """GET: everything the embedded labeling engine needs (config, image, the user's markup, AI suggestions).
    POST {result: [...]} saves the user's markup as their Label Studio annotation and syncs it to the dataset."""
    from tasks.models import Annotation, Prediction

    from .labeling import label_config_markup, sheet_image_url

    s = _get(Sheet, request, pk=pk)
    ensure_project(s.dataset)
    if not s.ls_task_id:
        from .labeling import ensure_tasks

        ensure_tasks(s.dataset, [s])
        s.refresh_from_db()
    tax = current_taxonomy(s.dataset)
    ann = Annotation.objects.filter(task_id=s.ls_task_id, completed_by=request.user, was_cancelled=False).order_by('-id').first()
    if request.method == 'POST':
        result = request.data.get('result')
        if not isinstance(result, list):
            raise ValidationError({'result': 'list required'})
        parent = None
        pid = request.data.get('from_suggestion')
        if pid:
            parent = Prediction.objects.filter(id=pid, task_id=s.ls_task_id).first()
        if ann is None:
            ann = Annotation.objects.create(task_id=s.ls_task_id, project_id=s.ls_task.project_id, result=result,
                                            completed_by=request.user, parent_prediction=parent)
        else:
            ann.result = result
            if parent and not ann.parent_prediction_id:
                ann.parent_prediction = parent
            ann.save()
        stats = sync_from_label_studio(s.dataset, [s])
        audit(request, 'markup.save', s, regions=len(result))
        return Response({'saved': True, 'annotation_id': ann.id, 'sync': stats,
                         'objects': CanonicalObject.objects.filter(sheet=s, deleted=False).count()})
    preds = [{'id': p.id, 'model_version': p.model_version, 'score': p.score, 'result': p.result}
             for p in Prediction.objects.filter(task_id=s.ls_task_id).order_by('-id')[:5]]
    pending = Proposal.objects.filter(sheet=s, kind=Proposal.Kind.CV_OBJECT, status='pending').count()
    sibs = list(s.dataset.sheets.order_by('id').values_list('id', flat=True))
    i = sibs.index(s.id)
    return Response({'sheet': _ser_sheet(s), 'config': label_config_markup(tax), 'dataset': {'id': s.dataset_id, 'name': s.dataset.name},
                     'prev': sibs[i - 1] if i > 0 else None, 'next': sibs[i + 1] if i + 1 < len(sibs) else None, 'position': [i + 1, len(sibs)],
                     'task': {'id': s.ls_task_id, 'data': {'image': sheet_image_url(s)}},
                     'annotation': {'id': ann.id, 'result': ann.result} if ann else None, 'predictions': preds,
                     'pending_suggestions': pending,
                     'dataset_counts': {r['label']: r['n'] for r in CanonicalObject.objects.filter(dataset=s.dataset, deleted=False).values('label').annotate(n=Count('id'))},
                     'classes': [c for c in tax.classes if c['kind'] == 'cv'],
                     'user': {'id': request.user.id, 'email': request.user.email}})


GOALS = {
    'outlines': {'task': 'semantic_segmentation', 'catalog_id': 'seg-dinov2-s'},
    'structure': {'task': 'node_classification', 'catalog_id': 'gnn-gps-node'},
    'relations': {'task': 'edge_classification', 'catalog_id': 'gnn-sage-edge'},
}


def _outline_choice(d) -> str:
    """Architecture for one-click 'outlines' training: the best-scoring architecture already trained on this plan set
    (so the run continues from it); otherwise the catalog default (DINOv2-S, per docs/kentucky/research/MODEL_REVIEW_2026-11.md)."""
    trained = [mv for mv in ModelVersion.objects.filter(organization=d.organization, dataset_version__dataset=d, status='ready',
                                                        model__task='semantic_segmentation').select_related('model')
               if catalog.get(mv.model.catalog_id) and catalog.get(mv.model.catalog_id).get('tier') != 'retired']
    if trained:  # the best-scoring one, not the newest: an experiment must not change the default
        return max(trained, key=lambda mv: ((TA.report_card(mv.metrics, mv.model.task) or {}).get('score') or 0, mv.created_at)).model.catalog_id
    return GOALS['outlines']['catalog_id']


@api_view(['POST'])
def dataset_train(request, pk):
    """One-click training: snapshot the project (immutable version) and create a validated job for the goal.
    If the org already has a model of the same type, it continues from it (fine-tune) unless fresh=true."""
    d = _get(Dataset, request, pk=pk)
    goal = GOALS.get(request.data.get('goal', 'outlines'))
    if goal is None:
        raise ValidationError({'goal': 'outlines | structure | relations'})
    if request.data.get('catalog_id'):  # advanced mode: explicit architecture / starting point / settings
        item = catalog.get(request.data['catalog_id'])
        if item is None:
            raise ValidationError({'catalog_id': 'unknown architecture'})
        goal = {'task': item['task'], 'catalog_id': item['id']}
    elif goal is GOALS['outlines']:
        goal = {**goal, 'catalog_id': _outline_choice(d)}
    v = create_version(d, request.user, notes='created by Train model')
    if not v.readiness['ready_for'].get(goal['task']):
        return Response({'ready': False, 'readiness': v.readiness, 'version_id': v.id}, status=200)
    base, init = None, request.data.get('init')
    if init == 'checkpoint' or (init is None and not request.data.get('fresh')):
        if request.data.get('base_model_version_id'):
            base = _get(ModelVersion, request, pk=request.data['base_model_version_id'])
        else:
            same = ModelVersion.objects.filter(organization=d.organization, model__catalog_id=goal['catalog_id'], status='ready')
            base = (same.filter(dataset_version__dataset=d).order_by('-created_at').first()  # this plan set's model first
                    or same.order_by('-created_at').first())
    if init is None:  # continue from your model, else the licensed pretrained start, else zero
        pre = next((i for i in (catalog.get(goal['catalog_id']) or {}).get('inits', []) if i['id'] == 'pretrained'), None)
        init = 'checkpoint' if base else ('pretrained' if pre and pre.get('commercially_deployable') is True else 'scratch')
    j = orch.create_job(d.organization, request.user, v, goal['catalog_id'], init,
                        request.data.get('config') or {}, base, request.data.get('gpu_type', 'cpu-local'),
                        request.data.get('name') or f'{d.name} — {"plan outlines" if goal["task"] == "semantic_segmentation" else "plan structure"}')
    audit(request, 'training.create', j, status=j.status, goal=request.data.get('goal'))
    return Response({'ready': True, 'job': _ser_job(j, full=True)}, status=201)


@api_view(['GET'])
def dataset_estimate(request, pk):
    """Up-front time/cost for the Train screen (before any job exists)."""
    from .training.config import ConfigError, validate

    d = _get(Dataset, request, pk=pk)
    goal = GOALS.get(request.GET.get('goal', 'outlines'), GOALS['outlines'])
    cid = request.GET.get('catalog_id') or (_outline_choice(d) if goal is GOALS['outlines'] else goal['catalog_id'])
    if catalog.get(cid) is None:
        raise ValidationError({'catalog_id': 'unknown architecture'})
    n = max(1, round(d.sheets.count() * 0.7))
    overrides = {k: request.GET[k] for k in ('epochs', 'batch_size', 'crops_per_sheet', 'training_scale') if request.GET.get(k)}
    try:
        cfg = validate(cid, overrides, {'train_items': n})
    except ConfigError as e:
        raise ValidationError({'detail': str(e)})
    caps = {g: pricing.runtime_cap(cid, cfg, n, g) for g in ('cpu-local', 'nvidia-t4', 'nvidia-a10g')}
    return Response({g: pricing.estimate_training(cid, {**cfg, 'max_runtime_s': caps[g]}, n, g) for g in caps})


@api_view(['GET'])
def training_defaults(request):
    """Recommended settings for an architecture plus the validation schema, for the Train screen's advanced mode."""
    from .training.config import ENUMS, SCHEMA, ConfigError, recommended

    cid = request.GET.get('catalog_id', '')
    n = int(request.GET.get('train_items') or 5)
    try:
        cfg = recommended(cid, {'train_items': n})
    except ConfigError as e:
        raise ValidationError({'catalog_id': str(e)})
    cfg['max_runtime_s'] = pricing.runtime_cap(cid, cfg, n, request.GET.get('gpu_type') or 'cpu-local')  # what the job gets
    return Response({'config': cfg, 'schema': {k: {'type': t.__name__, 'min': lo, 'max': hi} for k, (t, lo, hi) in SCHEMA.items() if k in cfg},
                     'enums': {k: sorted(v) for k, v in ENUMS.items() if k in cfg}})
