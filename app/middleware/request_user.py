import threading
from typing import Optional, Tuple, Dict, Any

from django.http import HttpRequest, HttpResponseRedirect

_thread_local = threading.local()


def get_current_request() -> Optional[HttpRequest]:
    return getattr(_thread_local, "request", None)


def get_current_user():
    req = get_current_request()
    if req is None:
        return None
    user = getattr(req, "user", None)
    return user if getattr(user, "is_authenticated", False) else None


def _client_ip_from_request(request: HttpRequest) -> Optional[str]:
    # Respect common proxy header first
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # may contain multiple IPs, client is first
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[0]
    return request.META.get("REMOTE_ADDR")


def get_request_meta() -> Dict[str, Any]:
    req = get_current_request()
    if not req:
        return {}
    return {
        "ip": _client_ip_from_request(req),
        "user_agent": req.META.get("HTTP_USER_AGENT"),
        "method": req.method,
        "path": req.get_full_path() if hasattr(req, "get_full_path") else req.path,
    }


class RequestUserMiddleware:
    """
    Store the current request in thread-local storage for downstream consumers
    like audit logging, signals, and services.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        _thread_local.request = request
        try:
            response = self.get_response(request)
        finally:
            # Clean up to avoid leaks on thread reuse
            try:
                del _thread_local.request
            except AttributeError:
                pass
        return response
