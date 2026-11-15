"""Private-by-default object storage for drawings, derived assets and model artifacts.

Keys are always prefixed with ``org_<id>/`` and resolved inside ``KA_STORAGE_ROOT``; any key that
escapes the root or the caller's org prefix is refused. ``LocalStorage`` is used in development; an
S3-compatible backend (Cloudflare R2) can be selected with ``KA_STORAGE_BACKEND=s3`` once
credentials are configured (see docs/kentucky/SECURITY.md). Downloads go through short-lived signed
URLs (``signed_url``) verified by ``kentucky.views.signed_file``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core import signing

SIGNING_SALT = 'kentucky.storage'
DEFAULT_TTL_S = 300


def root() -> Path:
    r = Path(getattr(settings, 'KA_STORAGE_ROOT', None) or os.path.join(settings.MEDIA_ROOT, 'kentucky'))
    r.mkdir(parents=True, exist_ok=True)
    return r


class StorageError(Exception):
    pass


def org_prefix(org_id: int) -> str:
    return f'org_{int(org_id)}'


def key(org_id: int, *parts: str) -> str:
    clean = []
    for p in parts:
        p = str(p).replace('\\', '/').strip('/')
        if not p or '..' in p.split('/'):
            raise StorageError('invalid key part')
        clean.append(p)
    return '/'.join([org_prefix(org_id), *clean])


def path(k: str, org_id: int | None = None) -> Path:
    if org_id is not None and not k.startswith(org_prefix(org_id) + '/'):
        raise StorageError('cross-organization storage access refused')
    p = (root() / k).resolve()
    if root().resolve() not in p.parents:
        raise StorageError('key escapes storage root')
    return p


def put_bytes(k: str, data: bytes) -> str:
    p = path(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return k


def put_file(k: str, src: str | Path) -> str:
    p = path(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, p)
    return k


def get_bytes(k: str, org_id: int | None = None) -> bytes:
    return path(k, org_id).read_bytes()


def exists(k: str) -> bool:
    return bool(k) and path(k).exists()


def delete_prefix(k: str, org_id: int):
    p = path(k, org_id)
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def signed_url(k: str, org_id: int, ttl_s: int = DEFAULT_TTL_S, filename: str | None = None) -> str:
    token = signing.dumps({'k': k, 'o': int(org_id), 'f': filename or ''}, salt=SIGNING_SALT)
    return f'/ka/files/signed/{token}?ttl={int(ttl_s)}'


def verify_signed(token: str, ttl_s: int = DEFAULT_TTL_S) -> dict:
    ttl_s = min(int(ttl_s), 3600)
    data = signing.loads(token, salt=SIGNING_SALT, max_age=ttl_s)
    path(data['k'], data['o'])  # re-check org prefix
    return data
