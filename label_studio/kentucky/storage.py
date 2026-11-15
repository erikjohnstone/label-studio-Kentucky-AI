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


def _check(k: str, org_id: int | None = None) -> str:
    if not k or k.startswith('/') or '..' in k.replace('\\', '/').split('/'):
        raise StorageError('invalid key')
    if org_id is not None and not k.startswith(org_prefix(org_id) + '/'):
        raise StorageError('cross-organization storage access refused')
    return k


def backend() -> str:
    return (getattr(settings, 'KA_STORAGE_BACKEND', None) or os.environ.get('KA_STORAGE_BACKEND') or 'local').lower()


_S3 = None


def _s3():
    """S3-compatible client (Cloudflare R2, AWS S3, MinIO). Configured only by the operator:
    KA_S3_BUCKET, KA_S3_ENDPOINT_URL (R2: https://<account>.r2.cloudflarestorage.com), KA_S3_REGION,
    credentials via the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment."""
    global _S3
    if _S3 is None:
        import boto3

        _S3 = boto3.client('s3', endpoint_url=getattr(settings, 'KA_S3_ENDPOINT_URL', None) or os.environ.get('KA_S3_ENDPOINT_URL') or None,
                           region_name=getattr(settings, 'KA_S3_REGION', None) or os.environ.get('KA_S3_REGION') or 'auto')
    return _S3


def _bucket() -> str:
    b = getattr(settings, 'KA_S3_BUCKET', None) or os.environ.get('KA_S3_BUCKET')
    if not b:
        raise StorageError('KA_S3_BUCKET is not configured')
    return b


def reset_client():
    global _S3
    _S3 = None


def path(k: str, org_id: int | None = None) -> Path:
    """Local filesystem path of a key (local backend only)."""
    _check(k, org_id)
    if backend() != 'local':
        raise StorageError('no local path for remote storage')
    p = (root() / k).resolve()
    if root().resolve() not in p.parents:
        raise StorageError('key escapes storage root')
    return p


def put_bytes(k: str, data: bytes) -> str:
    _check(k)
    if backend() == 's3':
        _s3().put_object(Bucket=_bucket(), Key=k, Body=data, ServerSideEncryption='AES256') if os.environ.get('KA_S3_SSE') == '1' \
            else _s3().put_object(Bucket=_bucket(), Key=k, Body=data)
        return k
    p = path(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return k


def put_file(k: str, src: str | Path) -> str:
    _check(k)
    if backend() == 's3':
        _s3().upload_file(str(src), _bucket(), k)
        return k
    p = path(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, p)
    return k


def get_bytes(k: str, org_id: int | None = None) -> bytes:
    _check(k, org_id)
    if backend() == 's3':
        try:
            return _s3().get_object(Bucket=_bucket(), Key=k)['Body'].read()
        except _s3().exceptions.NoSuchKey:
            raise FileNotFoundError(k)
    return path(k, org_id).read_bytes()


def exists(k: str) -> bool:
    if not k:
        return False
    _check(k)
    if backend() == 's3':
        r = _s3().list_objects_v2(Bucket=_bucket(), Prefix=k, MaxKeys=1)
        return any(o['Key'] == k or o['Key'].startswith(k.rstrip('/') + '/') for o in r.get('Contents', []))
    return path(k).exists()


def delete_prefix(k: str, org_id: int):
    _check(k, org_id)
    if backend() == 's3':
        c, b = _s3(), _bucket()
        for page in c.get_paginator('list_objects_v2').paginate(Bucket=b, Prefix=k):
            objs = [{'Key': o['Key']} for o in page.get('Contents', []) if o['Key'] == k or o['Key'].startswith(k.rstrip('/') + '/')]
            if objs:
                c.delete_objects(Bucket=b, Delete={'Objects': objs})
        return
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
    _check(data['k'], data['o'])  # re-check org prefix
    return data
