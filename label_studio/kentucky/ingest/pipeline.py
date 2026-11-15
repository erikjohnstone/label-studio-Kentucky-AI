"""Upload -> validate -> store -> extract -> tile -> sheets -> annotation tasks."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile

from django.db import transaction

from .. import coords, storage
from ..models import SCHEMA_VERSION, Provenance, Sheet, SourceDocument

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.dxf'}
UNSUPPORTED_EXPLICIT = {
    '.dwg': 'DWG is not natively supported yet: export to DXF (a DWG->DXF converter service is a documented extension point).',
    '.ifc': 'IFC is not supported yet (no parser implemented).',
}


class IngestError(ValueError):
    pass


def sniff(filename: str, data: bytes) -> str:
    """Validate type by magic bytes, not by extension alone. Returns a SourceDocument.Kind-ish string."""
    name = filename.lower()
    ext = '.' + name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext in UNSUPPORTED_EXPLICIT:
        raise IngestError(UNSUPPORTED_EXPLICIT[ext])
    if ext not in ALLOWED_EXT:
        raise IngestError(f'Unsupported file type {ext or "(none)"}; allowed: PDF, PNG, JPG, DXF')
    if len(data) == 0:
        raise IngestError('Empty file')
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError('File exceeds 200 MB upload limit')
    head = data[:1024]
    if ext == '.pdf':
        if not head.startswith(b'%PDF-'):
            raise IngestError('File does not look like a PDF')
        lowered = data[: 2_000_000]
        if b'/Encrypt' in lowered:
            raise IngestError('Encrypted PDFs are not accepted')
        if b'/JavaScript' in lowered or b'/Launch' in lowered:
            raise IngestError('PDF contains active content (JavaScript/Launch actions) and was rejected')
        return 'pdf'
    if ext == '.png':
        if not head.startswith(b'\x89PNG\r\n\x1a\n'):
            raise IngestError('File does not look like a PNG')
        return 'image'
    if ext in ('.jpg', '.jpeg'):
        if not head.startswith(b'\xff\xd8'):
            raise IngestError('File does not look like a JPEG')
        return 'image'
    if ext == '.dxf':
        txt = head.decode('utf-8', errors='ignore')
        if 'SECTION' not in txt and 'AutoCAD Binary DXF' not in txt:
            raise IngestError('File does not look like a DXF')
        if head.startswith(b'AutoCAD Binary DXF'):
            raise IngestError('Binary DXF is not supported; save as ASCII DXF')
        return 'dxf'
    raise IngestError('Unsupported file')


def create_document(dataset, filename: str, data: bytes, user=None, split_group: str = '') -> SourceDocument:
    sniff(filename, data)
    digest = hashlib.sha256(data).hexdigest()
    org_id = dataset.organization_id
    k = storage.key(org_id, 'datasets', dataset.id, 'originals', f'{digest}_{_safe(filename)}')
    storage.put_bytes(k, data)
    return SourceDocument.objects.create(
        organization_id=org_id, dataset=dataset, filename=filename[:500], sha256=digest, size_bytes=len(data),
        storage_key=k, uploaded_by=user, split_group=split_group or filename.rsplit('.', 1)[0][:200],
    )


def _safe(name: str) -> str:
    keep = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)
    return keep[-120:] or 'file'


def process_document(doc: SourceDocument, create_tasks: bool = True) -> list[Sheet]:
    from . import extract

    data = storage.get_bytes(doc.storage_key, doc.organization_id)
    doc.status = SourceDocument.Status.PROCESSING
    doc.save(update_fields=['status'])
    try:
        kind = sniff(doc.filename, data)
        if kind == 'pdf':
            extracts = extract.extract_pdf(data)
        elif kind == 'dxf':
            extracts = extract.extract_dxf(data)
        else:
            extracts = extract.extract_image(data)
    except Exception as e:  # noqa: BLE001
        logger.exception('ingest failed')
        doc.status = SourceDocument.Status.REJECTED if isinstance(e, IngestError) else SourceDocument.Status.FAILED
        doc.error = str(e)[:2000]
        doc.save(update_fields=['status', 'error'])
        raise
    if kind == 'pdf':
        doc.kind = SourceDocument.Kind.PDF_VECTOR if any(x.has_vector for x in extracts) else SourceDocument.Kind.PDF_RASTER
    elif kind == 'dxf':
        doc.kind = SourceDocument.Kind.DXF
    else:
        doc.kind = SourceDocument.Kind.IMAGE
    sheets = []
    with transaction.atomic():
        for ex in extracts:
            sheets.append(_store_sheet(doc, ex))
        doc.status = SourceDocument.Status.READY
        doc.metadata = {**doc.metadata, 'pages': len(extracts)}
        doc.save(update_fields=['status', 'kind', 'metadata'])
    if create_tasks:
        from ..labeling import ensure_tasks

        ensure_tasks(doc.dataset, sheets)
    return sheets


def _store_sheet(doc: SourceDocument, ex) -> Sheet:
    org = doc.organization_id
    base = ('datasets', doc.dataset_id, 'sheets', f'{doc.id}_{ex.page_index}')
    buf = io.BytesIO()
    ex.image.save(buf, format='PNG', optimize=True)
    image_key = storage.put_bytes(storage.key(org, *base, 'image.png'), buf.getvalue())
    tiles_key, levels = _tiles(org, base, ex.image)
    vector_prov = Provenance.IMPORT if ex.has_vector else (
        Provenance.RASTER_INFERRED if ex.vector_provenance == 'raster_inferred' else Provenance.IMPORT
    )
    sheet = Sheet.objects.create(
        organization_id=org, document=doc, dataset_id=doc.dataset_id, page_index=ex.page_index,
        name=f'{doc.filename} - {ex.name}', width=ex.image.width, height=ex.image.height, rotation=ex.rotation,
        source_units=ex.source_units, source_to_image=coords.to_list(ex.source_to_image), has_vector=ex.has_vector,
        vector_provenance=vector_prov, image_key=image_key, tiles_key=tiles_key, tile_levels=levels,
        primitive_count=sum(1 for p in ex.primitives if p['type'] != 'text'),
        text_count=sum(1 for p in ex.primitives if p['type'] == 'text'), ocr_status=ex.ocr_status,
    )
    payload = {
        'schema_version': SCHEMA_VERSION, 'sheet_id': sheet.id, 'document_id': doc.id, 'source_units': ex.source_units,
        'source_to_image': coords.to_list(ex.source_to_image), 'image_size': [ex.image.width, ex.image.height],
        'vector_provenance': vector_prov, 'metadata': ex.metadata, 'primitives': ex.primitives,
    }
    sheet.primitives_key = storage.put_bytes(storage.key(org, *base, 'primitives.json'), json.dumps(payload).encode())
    sheet.save(update_fields=['primitives_key'])
    return sheet


def _tiles(org, base, image):
    """Image pyramid (512px PNG tiles, zip per sheet). Level L is downsampled by 2**L."""
    levels = coords.pyramid_levels(image.width, image.height)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        for lvl in range(levels):
            f = 2**lvl
            im = image if lvl == 0 else image.resize((max(1, image.width // f), max(1, image.height // f)))
            T = coords.TILE_SIZE
            for row in range(0, (im.height + T - 1) // T):
                for col in range(0, (im.width + T - 1) // T):
                    tile = im.crop((col * T, row * T, min((col + 1) * T, im.width), min((row + 1) * T, im.height)))
                    tb = io.BytesIO()
                    tile.save(tb, format='PNG')
                    zf.writestr(f'{lvl}/{col}_{row}.png', tb.getvalue())
    return storage.put_bytes(storage.key(org, *base, 'tiles.zip'), buf.getvalue()), levels


def load_primitives(sheet: Sheet) -> dict:
    if not sheet.primitives_key:
        return {'primitives': []}
    return json.loads(storage.get_bytes(sheet.primitives_key, sheet.organization_id))


def read_tile(sheet: Sheet, level: int, col: int, row: int) -> bytes:
    with zipfile.ZipFile(io.BytesIO(storage.get_bytes(sheet.tiles_key, sheet.organization_id))) as zf:
        return zf.read(f'{int(level)}/{int(col)}_{int(row)}.png')
