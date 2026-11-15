"""Tenant isolation, API-key auth, rate limiting and audit logging."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from .models import ApiKey, AuditLog


def org_of(request):
    """Active organization of the authenticated principal (user session/token or API key)."""
    if getattr(request, 'ka_api_key', None) is not None:
        return request.ka_api_key.organization
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        raise exceptions.NotAuthenticated()
    org = user.active_organization
    if org is None:
        raise exceptions.PermissionDenied('No active organization')
    if not org.has_user(user):
        raise exceptions.PermissionDenied('Not a member of the active organization')
    return org


class OrgScopedMixin:
    """DRF mixin: every queryset is filtered by the caller's organization."""

    model = None

    def org(self):
        return org_of(self.request)

    def scoped(self, model=None, **filters):
        model = model or self.model
        return model.objects.filter(organization=self.org(), **filters)

    def get_scoped(self, model, **filters):
        obj = model.objects.filter(organization=self.org(), **filters).first()
        if obj is None:
            # Same response whether the object does not exist or belongs to another org.
            raise exceptions.NotFound()
        return obj


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer ka_...`` organization API keys (inference endpoints)."""

    keyword = 'Bearer'

    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith('Bearer ka_'):
            return None
        raw = header.split(' ', 1)[1].strip()
        key = ApiKey.objects.select_related('organization').filter(key_hash=ApiKey.hash(raw), revoked_at=None).first()
        if key is None:
            raise exceptions.AuthenticationFailed('Invalid or revoked API key')
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        request._request.ka_api_key = key
        request.ka_api_key = key
        return (key.created_by, key)


class HasApiKeyScope(permissions.BasePermission):
    scope = 'inference'

    def has_permission(self, request, view):
        key = getattr(request, 'ka_api_key', None)
        if key is not None:
            return self.scope in (key.scopes or [])
        return bool(request.user and request.user.is_authenticated)


class RateLimiter:
    """In-process sliding-window limiter. Replace with Redis for multi-process deployments."""

    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = Lock()

    def allow(self, bucket: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[bucket]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self.lock:
            self.hits.clear()


rate_limiter = RateLimiter()


def audit(request_or_org, action: str, target=None, **data):
    request = None
    if hasattr(request_or_org, 'META'):
        request = request_or_org
        org = org_of(request)
    else:
        org = request_or_org
    actor = None
    key = None
    ip = ''
    if request is not None:
        key = getattr(request, 'ka_api_key', None)
        u = getattr(request, 'user', None)
        actor = u if (u is not None and u.is_authenticated) else None
        ip = request.META.get('REMOTE_ADDR', '')
    AuditLog.objects.create(
        organization=org, actor=actor, api_key=key, action=action,
        target_type=type(target).__name__ if target is not None else '',
        target_id=str(getattr(target, 'pk', '') or ''), data=data, ip=ip,
    )
