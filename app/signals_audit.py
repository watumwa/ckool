from __future__ import annotations

import datetime
import decimal
from typing import Any, Dict, Optional

from django.db.models.signals import pre_save, post_save, post_delete
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models

from app.models.audit import AuditLog
from app.middleware.request_user import get_current_user, get_request_meta

_audit_table_known_exists = None


# ---------------------------
# Serialization helpers
# ---------------------------
def _serialize_value(val: Any) -> Any:
    """
    Convert values to JSON-serializable types.
    """
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    if isinstance(val, decimal.Decimal):
        # keep precision as string to avoid float rounding, or float(val) if preferred
        return str(val)
    if isinstance(val, (datetime.date, datetime.datetime, datetime.time)):
        # use ISO format for temporal values
        try:
            return val.isoformat()
        except Exception:
            return str(val)
    if isinstance(val, bytes):
        # don't dump huge binary blobs; just length + repr slice
        return f"<bytes len={len(val)}>"
    # FKs & model instances -> prefer pk if present, else str()
    if hasattr(val, "pk"):
        try:
            return {"pk": val.pk, "repr": str(val)}
        except Exception:
            return {"pk": getattr(val, "pk", None), "repr": str(val)}
    # Fall back to string
    return str(val)


def _extract_state(obj: models.Model) -> Dict[str, Any]:
    """
    Extract a dictionary of the object's concrete field values.
    For FK fields, use the raw column (attname) value to capture the PK.
    """
    state: Dict[str, Any] = {}
    for field in obj._meta.concrete_fields:
        try:
            # For FK, attname holds the raw db column (e.g., user_id)
            attr_name = getattr(field, "attname", field.name)
            value = getattr(obj, attr_name, None)
            state[field.name] = _serialize_value(value)
        except Exception:
            # Guard against any odd field access failures
            state[field.name] = "<unavailable>"
    return state


def _diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Return a dict of changed fields: {field: {"old": ..., "new": ...}}
    """
    delta: Dict[str, Dict[str, Any]] = {}
    keys = set(old.keys()) | set(new.keys())
    for k in keys:
        if old.get(k) != new.get(k):
            delta[k] = {"old": old.get(k), "new": new.get(k)}
    return delta


def _is_audit_model(instance: models.Model) -> bool:
    return isinstance(instance, AuditLog)


def _build_common_meta() -> Dict[str, Any]:
    user = get_current_user()
    req_meta = get_request_meta() or {}
    return {
        "user": user,
        "username": getattr(user, "username", "") if user else "",
        "ip": req_meta.get("ip"),
        "user_agent": req_meta.get("user_agent"),
        "method": req_meta.get("method"),
        "path": req_meta.get("path"),
    }


def _audit_table_exists() -> bool:
    global _audit_table_known_exists
    if _audit_table_known_exists is True:
        return True

    try:
        table_name = AuditLog._meta.db_table
        exists = table_name in connection.introspection.table_names()
        if exists:
            _audit_table_known_exists = True
        return exists
    except Exception:
        return False


def _save_audit_entry(
    *,
    action: str,
    instance: Optional[models.Model] = None,
    changes: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Persist an AuditLog with current request/user context.
    """
    meta = _build_common_meta()
    user = meta["user"]
    username = meta["username"]
    ip = meta["ip"]
    ua = meta["user_agent"]
    method = meta["method"]
    path = meta["path"]

    ct = None
    obj_id = ""
    obj_repr = ""

    if instance is not None:
        try:
            ct = ContentType.objects.get_for_model(instance.__class__)
        except Exception:
            ct = None
        try:
            obj_id = str(getattr(instance, "pk", "") or "")
        except Exception:
            obj_id = ""
        try:
            obj_repr = str(instance)
        except Exception:
            # fallback to model label with ID
            model_label = f"{instance._meta.app_label}.{instance._meta.model_name}"  # type: ignore[attr-defined]
            obj_repr = f"{model_label}({obj_id})"

    if not _audit_table_exists():
        return

    try:
        AuditLog.objects.create(
            user=user if user else None,
            username=username or "",
            ip_address=ip,
            user_agent=ua or "",
            method=method or "",
            path=path or "",
            action=action,
            content_type=ct,
            object_id=obj_id,
            object_repr=obj_repr,
            changes=changes or None,
            extra=extra or None,
        )
    except Exception:
        # Never break the main flow because of auditing issues
        pass


# ---------------------------
# Model lifecycle auditing
# ---------------------------

@receiver(pre_save)
def audit_pre_save(sender, instance: models.Model, **kwargs):
    # Skip Django internal models we don't care about or recursive logging
    if _is_audit_model(instance):
        return
    # Only audit concrete models
    if not isinstance(instance, models.Model):
        return
    # Snapshot current DB state if updating existing row
    try:
        if getattr(instance, "pk", None):
            model_cls = instance.__class__
            try:
                db_obj = model_cls.objects.get(pk=instance.pk)
                setattr(instance, "_audit_old_state", _extract_state(db_obj))
            except model_cls.DoesNotExist:  # type: ignore[attr-defined]
                setattr(instance, "_audit_old_state", {})
    except Exception:
        # If anything goes wrong, just proceed
        setattr(instance, "_audit_old_state", {})


@receiver(post_save)
def audit_post_save(sender, instance: models.Model, created: bool, **kwargs):
    if _is_audit_model(instance):
        return
    if not isinstance(instance, models.Model):
        return

    try:
        new_state = _extract_state(instance)
        if created:
            # Log creation with full new state
            _save_audit_entry(
                action=AuditLog.ACTION_CREATE,
                instance=instance,
                changes={"new": new_state},
            )
        else:
            old_state = getattr(instance, "_audit_old_state", {}) or {}
            delta = _diff(old_state, new_state)
            if delta:
                _save_audit_entry(
                    action=AuditLog.ACTION_UPDATE,
                    instance=instance,
                    changes=delta,
                )
            # else: no material change; skip to reduce noise
    except Exception:
        # Ensure we never raise
        pass


@receiver(post_delete)
def audit_post_delete(sender, instance: models.Model, **kwargs):
    if _is_audit_model(instance):
        return
    if not isinstance(instance, models.Model):
        return
    try:
        # Capture last known state for context
        last_state = _extract_state(instance)
        _save_audit_entry(
            action=AuditLog.ACTION_DELETE,
            instance=instance,
            changes={"old": last_state},
        )
    except Exception:
        pass


# ---------------------------
# Authentication auditing
# ---------------------------

@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    try:
        _save_audit_entry(
            action=AuditLog.ACTION_LOGIN,
            instance=None,
            changes=None,
            extra={"username": getattr(user, "username", "")},
        )
    except Exception:
        pass


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    try:
        _save_audit_entry(
            action=AuditLog.ACTION_LOGOUT,
            instance=None,
            changes=None,
            extra={"username": getattr(user, "username", "")},
        )
    except Exception:
        pass


@receiver(user_login_failed)
def audit_user_login_failed(sender, credentials, request, **kwargs):
    try:
        # Don't store raw passwords; only username for context
        username = (credentials or {}).get("username", "")
        _save_audit_entry(
            action=AuditLog.ACTION_LOGIN,
            instance=None,
            changes=None,
            extra={"username": username, "status": "failed"},
        )
    except Exception:
        pass
