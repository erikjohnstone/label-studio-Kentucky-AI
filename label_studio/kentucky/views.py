"""Server-rendered shells for the Kentucky AI platform UI + org-checked file serving."""

from __future__ import annotations

import mimetypes

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import storage
from .ingest.pipeline import read_tile
from .models import Sheet

PAGES = {
    'home': 'Datasets', 'project': 'Project', 'markup': 'Mark up plan', 'graph': 'Plan structure', 'models': 'Models',
    'train': 'Train a model', 'run': 'Training', 'deployments': 'Deployments', 'apikeys': 'API keys', 'api': 'API docs',
    'billing': 'Billing', 'team': 'Team & settings',
}


def _org(request):
    org = request.user.active_organization
    if org is None or not org.has_user(request.user):
        raise Http404()
    return org


@login_required
def page(request, name='home', pk=None):
    if name not in PAGES:
        raise Http404()
    _org(request)
    return render(request, 'kentucky/app.html', {'page': name, 'title': PAGES[name], 'pk': pk or '', 'user_email': request.user.email,
                                                 'org_title': request.user.active_organization.title})


@login_required
@require_GET
def sheet_image(request, pk):
    org = _org(request)
    s = Sheet.objects.filter(pk=pk, organization=org).first()
    if s is None:
        raise Http404()
    resp = HttpResponse(storage.get_bytes(s.image_key, org.id), content_type='image/png')
    resp['Cache-Control'] = 'private, max-age=600'
    return resp


@login_required
@require_GET
def sheet_tile(request, pk, level, col, row):
    org = _org(request)
    s = Sheet.objects.filter(pk=pk, organization=org).first()
    if s is None:
        raise Http404()
    try:
        data = read_tile(s, level, col, row)
    except KeyError:
        raise Http404()
    resp = HttpResponse(data, content_type='image/png')
    resp['Cache-Control'] = 'private, max-age=3600'
    return resp


@require_GET
def signed_file(request, token):
    """Short-lived signed download (default 5 min, max 1h). Works without a session, e.g. for API clients."""
    try:
        data = storage.verify_signed(token, int(request.GET.get('ttl', storage.DEFAULT_TTL_S)))
    except (signing.BadSignature, signing.SignatureExpired, storage.StorageError, ValueError):
        raise Http404()
    p = storage.path(data['k'], data['o'])
    if not p.exists():
        raise Http404()
    ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
    resp = HttpResponse(p.read_bytes(), content_type=ctype)
    resp['Content-Disposition'] = f'attachment; filename="{data.get("f") or p.name}"'
    resp['Cache-Control'] = 'no-store'
    return resp


ENGINE_ROOT = None


def engine_asset(request, path):
    """Serve the embedded labeling engine (Label Studio editor library, Apache-2.0) under our own path."""
    import os

    from django.conf import settings
    from django.views.static import serve

    root = os.path.realpath(os.path.join(settings.BASE_DIR, '../../web/dist/libs/editor'))
    resp = serve(request, path, document_root=root)
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp
