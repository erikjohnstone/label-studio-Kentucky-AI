"""Kentucky AI platform data model.

Every row is scoped to an ``organizations.Organization``. All API querysets filter on
``organization=request_org`` (see ``kentucky.security``). The canonical construction-object
schema (CV + graph) is described in ``docs/kentucky/DATASET_SCHEMA.md``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

SCHEMA_VERSION = '1.0'


def new_uid(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


class OrgScoped(models.Model):
    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Review(models.TextChoices):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class Provenance(models.TextChoices):
    HUMAN = 'human'  # drawn by a person
    AGENT = 'agent'  # proposed by a labeling agent, not yet accepted
    AGENT_ACCEPTED = 'agent_accepted'  # agent proposal accepted (possibly edited) by a human
    MODEL = 'model'  # prediction from a trained model
    GEOMETRIC = 'geometric'  # derived by deterministic geometry rules (candidate, not semantic truth)
    RASTER_INFERRED = 'raster_inferred'  # vectorized from pixels, NOT verified CAD geometry
    IMPORT = 'import'


# --------------------------------------------------------------------------- datasets
class Dataset(OrgScoped):
    TASKS = ['semantic_segmentation', 'instance_segmentation', 'node_classification', 'edge_classification']
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    project = models.OneToOneField(
        'projects.Project', null=True, blank=True, on_delete=models.SET_NULL, related_name='ka_dataset'
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    # Customer consent that Kentucky AI may use this data to train its own models (default: NO).
    allow_ka_model_training = models.BooleanField(default=False)
    consent_record = models.JSONField(default=dict, blank=True)
    archived = models.BooleanField(default=False)


class Taxonomy(OrgScoped):
    """Versioned class list. ``classes``: [{name, kind: cv|node|edge, color, aliases[], trade, description}]"""

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='taxonomies')
    version = models.PositiveIntegerField()
    classes = models.JSONField(default=list)
    frozen = models.BooleanField(default=False)

    class Meta:
        unique_together = [('dataset', 'version')]
        ordering = ['-version']

    def resolve(self, label: str, kind: str | None = None) -> str | None:
        """Map a label or alias to its canonical class name."""
        low = (label or '').strip().lower()
        for c in self.classes:
            if kind and c.get('kind') != kind:
                continue
            if c['name'].lower() == low or low in [a.lower() for a in c.get('aliases', [])]:
                return c['name']
        return None

    def names(self, kind: str) -> list[str]:
        return [c['name'] for c in self.classes if c.get('kind') == kind]


class SourceDocument(OrgScoped):
    class Kind(models.TextChoices):
        PDF_VECTOR = 'pdf_vector'
        PDF_RASTER = 'pdf_raster'
        IMAGE = 'image'
        DXF = 'dxf'

    class Status(models.TextChoices):
        UPLOADED = 'uploaded'
        PROCESSING = 'processing'
        READY = 'ready'
        FAILED = 'failed'
        REJECTED = 'rejected'

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='documents')
    filename = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.BigIntegerField(default=0)
    kind = models.CharField(max_length=20, choices=Kind.choices, blank=True, default='')
    storage_key = models.CharField(max_length=1000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    error = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    # Group used for leakage-free splits (a building or construction project).
    split_group = models.CharField(max_length=200, blank=True, default='')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')


class Sheet(OrgScoped):
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='sheets')
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='sheets')
    page_index = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=300, blank=True, default='')
    width = models.PositiveIntegerField()  # rendered image px
    height = models.PositiveIntegerField()
    rotation = models.IntegerField(default=0)
    source_units = models.CharField(max_length=20, default='pt')  # pt | cad_units | px
    source_to_image = models.JSONField()  # 3x3 affine, see kentucky.coords
    has_vector = models.BooleanField(default=False)
    vector_provenance = models.CharField(max_length=20, choices=Provenance.choices, default=Provenance.IMPORT)
    image_key = models.CharField(max_length=1000)
    tiles_key = models.CharField(max_length=1000, blank=True, default='')
    tile_levels = models.PositiveIntegerField(default=1)
    primitives_key = models.CharField(max_length=1000, blank=True, default='')
    primitive_count = models.PositiveIntegerField(default=0)
    text_count = models.PositiveIntegerField(default=0)
    ocr_status = models.CharField(max_length=40, default='not_needed')
    ls_task = models.OneToOneField('tasks.Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='ka_sheet')
    labeling_status = models.CharField(max_length=20, default='unlabeled')  # unlabeled|in_progress|labeled|reviewed

    class Meta:
        ordering = ['document_id', 'page_index']


# --------------------------------------------------------------------------- canonical objects + graph
class CanonicalObject(OrgScoped):
    """One construction object (a wall, a door ...). Shared identity across CV + graph annotations.

    geometry: {bbox:[x,y,w,h] (image px), polygon:[[x,y],...] (image px), mask_rle?:{size,counts}}
    """

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='canonical_objects')
    sheet = models.ForeignKey(Sheet, on_delete=models.CASCADE, related_name='canonical_objects')
    uid = models.CharField(max_length=40, unique=True, default='')
    label = models.CharField(max_length=200)
    geometry_type = models.CharField(max_length=20, default='polygon')  # polygon|bbox|mask|point|polyline
    geometry = models.JSONField(default=dict)
    primitive_ids = models.JSONField(default=list, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    provenance = models.CharField(max_length=20, choices=Provenance.choices, default=Provenance.HUMAN)
    proposal = models.ForeignKey('Proposal', null=True, blank=True, on_delete=models.SET_NULL, related_name='canonical_objects')
    review_status = models.CharField(max_length=20, choices=Review.choices, default=Review.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    annotator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    ls_annotation_id = models.IntegerField(null=True, blank=True, db_index=True)
    ls_result_id = models.CharField(max_length=100, blank=True, default='')
    is_negative = models.BooleanField(default=False)  # explicit background / "nothing here" example
    deleted = models.BooleanField(default=False)
    schema_version = models.CharField(max_length=10, default=SCHEMA_VERSION)
    history = models.JSONField(default=list, blank=True)  # [{at, by, action, before}]

    def save(self, *a, **kw):
        if not self.uid:
            self.uid = new_uid('obj')
        super().save(*a, **kw)


class SheetGraph(OrgScoped):
    """Versioned graph annotation for a sheet. Each save creates a new version (append-only).

    graph = {schema_version, nodes:[{id, type, label, primitive_ids, object_uid, features, bbox,
             provenance, review, confidence}], edges:[{id, source, target, type, label, directed,
             provenance, review, confidence, features}], graph_labels:{}}
    """

    sheet = models.ForeignKey(Sheet, on_delete=models.CASCADE, related_name='graphs')
    version = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True, db_index=True)
    graph = models.JSONField()
    stats = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=40, default='builder')  # builder|human|agent|model
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    review_status = models.CharField(max_length=20, choices=Review.choices, default=Review.PENDING)
    message = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        unique_together = [('sheet', 'version')]
        ordering = ['-version']


class Proposal(OrgScoped):
    """A suggestion from an agent or model. Never ground truth until a human accepts it."""

    class Kind(models.TextChoices):
        CV_OBJECT = 'cv_object'
        NODE_LABEL = 'node_label'
        EDGE = 'edge'
        GROUP = 'group'
        CLASS_SUGGESTION = 'class_suggestion'
        QUALITY_FLAG = 'quality_flag'

    class Status(models.TextChoices):
        PENDING = 'pending'
        ACCEPTED = 'accepted'
        MODIFIED = 'modified'  # accepted with human edits
        REJECTED = 'rejected'
        DISMISSED = 'dismissed'

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='proposals')
    sheet = models.ForeignKey(Sheet, null=True, blank=True, on_delete=models.CASCADE, related_name='proposals')
    kind = models.CharField(max_length=30, choices=Kind.choices)
    agent = models.CharField(max_length=100)  # e.g. ka-geometry-agent
    agent_version = models.CharField(max_length=50)
    model_version = models.ForeignKey('ModelVersion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    confidence = models.FloatField(null=True, blank=True)
    payload = models.JSONField()  # the original proposal, never mutated
    evidence = models.JSONField(default=dict, blank=True)  # why: rule, primitive ids, text spans, scores
    explanation = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    final_payload = models.JSONField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    ls_prediction_id = models.IntegerField(null=True, blank=True)


class DatasetVersion(OrgScoped):
    """Immutable snapshot. ``manifest`` lists every sheet + approved object + graph version used."""

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    taxonomy = models.JSONField()
    manifest = models.JSONField()
    splits = models.JSONField()  # {train:[sheet_ids], val:[...], test:[...], strategy, seed, groups}
    readiness = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    export_key = models.CharField(max_length=1000, blank=True, default='')
    export_formats = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('dataset', 'version')]
        ordering = ['-version']


# --------------------------------------------------------------------------- training
class JobStatus(models.TextChoices):
    CREATED = 'CREATED'
    VALIDATING = 'VALIDATING'
    QUEUED = 'QUEUED'
    PROVISIONING = 'PROVISIONING'
    PREPARING = 'PREPARING'
    TRAINING = 'TRAINING'
    EVALUATING = 'EVALUATING'
    SAVING = 'SAVING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'
    TIMED_OUT = 'TIMED_OUT'


TERMINAL_STATES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMED_OUT}


class TrainingJob(OrgScoped):
    dataset_version = models.ForeignKey(DatasetVersion, on_delete=models.PROTECT, related_name='jobs')
    name = models.CharField(max_length=200, blank=True, default='')
    task = models.CharField(max_length=40)
    catalog_id = models.CharField(max_length=100)  # kentucky.catalog entry id
    init = models.CharField(max_length=20)  # scratch | pretrained | kentucky | checkpoint
    base_model_version = models.ForeignKey('ModelVersion', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    config = models.JSONField()  # fully-resolved hyperparameters (reproducibility)
    seed = models.IntegerField(default=0)
    code_version = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.CREATED, db_index=True)
    status_history = models.JSONField(default=list)
    provider = models.CharField(max_length=30, default='local')
    provider_job_id = models.CharField(max_length=200, blank=True, default='')
    gpu_type = models.CharField(max_length=40, default='cpu')
    estimate = models.JSONField(default=dict)
    max_cost_usd = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    max_runtime_s = models.PositiveIntegerField(default=3600)
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    authorized_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    cancel_requested = models.BooleanField(default=False)
    attempt = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=2)
    worker_id = models.CharField(max_length=100, blank=True, default='')
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    job_dir = models.CharField(max_length=1000, blank=True, default='')
    metrics_history = models.JSONField(default=list)  # [{epoch, step, train_loss, val_loss, ...}]
    final_metrics = models.JSONField(default=dict)
    resource_usage = models.JSONField(default=dict)
    error = models.TextField(blank=True, default='')
    events_offset = models.BigIntegerField(default=0)


class RegisteredModel(OrgScoped):
    name = models.CharField(max_length=200)
    task = models.CharField(max_length=40)
    catalog_id = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    archived = models.BooleanField(default=False)

    class Meta:
        unique_together = [('organization', 'name')]


class ModelVersion(OrgScoped):
    model = models.ForeignKey(RegisteredModel, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    training_job = models.ForeignKey(TrainingJob, null=True, blank=True, on_delete=models.SET_NULL, related_name='model_versions')
    dataset_version = models.ForeignKey(DatasetVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    artifact_key = models.CharField(max_length=1000)
    artifact_sha256 = models.CharField(max_length=64)
    metrics = models.JSONField(default=dict)
    input_schema = models.JSONField(default=dict)
    output_schema = models.JSONField(default=dict)
    label_map = models.JSONField(default=dict)
    license = models.JSONField(default=dict)
    downloadable = models.BooleanField(default=True)
    status = models.CharField(max_length=20, default='ready')  # ready|archived

    class Meta:
        unique_together = [('model', 'version')]
        ordering = ['-version']


class Deployment(OrgScoped):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    model = models.ForeignKey(RegisteredModel, on_delete=models.CASCADE, related_name='deployments')
    active_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, related_name='+')
    history = models.JSONField(default=list)  # [{version_id, at, by, action}]
    status = models.CharField(max_length=20, default='active')  # active|paused|deleted
    kind = models.CharField(max_length=20, default='serverless')  # serverless|dedicated
    rate_limit_per_minute = models.PositiveIntegerField(default=60)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    request_count = models.BigIntegerField(default=0)
    error_count = models.BigIntegerField(default=0)
    last_request_at = models.DateTimeField(null=True, blank=True)


class ApiKey(OrgScoped):
    name = models.CharField(max_length=200)
    prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)  # inference, read
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    rotated_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def generate(cls, organization, name, user=None, scopes=None, rotated_from=None):
        raw = 'ka_' + secrets.token_urlsafe(32)
        obj = cls.objects.create(
            organization=organization, name=name, prefix=raw[:10], key_hash=cls.hash(raw),
            scopes=scopes or ['inference'], created_by=user, rotated_from=rotated_from,
        )
        return obj, raw


# --------------------------------------------------------------------------- billing
class BillingAccount(OrgScoped):
    stripe_customer_id = models.CharField(max_length=100, blank=True, default='')
    payment_method_status = models.CharField(max_length=30, default='none')  # none|test_card|active
    monthly_spend_cap_usd = models.DecimalField(max_digits=12, decimal_places=2, default=100)
    prepaid_credit_usd = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    stripe_mode = models.CharField(max_length=10, default='test')


class LedgerEntry(OrgScoped):
    """Append-only usage + charge ledger. ``idempotency_key`` makes every billable event unique."""

    class Kind(models.TextChoices):
        TRAINING_COMPUTE = 'training_compute'
        TRAINING_PLATFORM_FEE = 'training_platform_fee'
        INFERENCE = 'inference'
        HOSTING = 'hosting'
        STORAGE = 'storage'
        CREDIT = 'credit'
        ADJUSTMENT = 'adjustment'

    kind = models.CharField(max_length=30, choices=Kind.choices)
    idempotency_key = models.CharField(max_length=200, unique=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    unit = models.CharField(max_length=30)
    infra_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    customer_charge_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    reference_type = models.CharField(max_length=40, blank=True, default='')
    reference_id = models.CharField(max_length=100, blank=True, default='')
    description = models.CharField(max_length=500, blank=True, default='')
    stripe_status = models.CharField(max_length=30, default='not_submitted')
    stripe_ref = models.CharField(max_length=200, blank=True, default='')


class AuditLog(OrgScoped):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    api_key = models.ForeignKey(ApiKey, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=60, blank=True, default='')
    target_id = models.CharField(max_length=100, blank=True, default='')
    data = models.JSONField(default=dict, blank=True)
    ip = models.CharField(max_length=64, blank=True, default='')
