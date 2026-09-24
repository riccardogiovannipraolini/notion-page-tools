"""Safe, reversible Notion page trash/restore handlers.

The official Notion REST API calls page deletion "trashing". This plugin never
permanently deletes a page: it sets ``in_trash`` and verifies the result.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2026-03-11"
_REQUEST_TIMEOUT_SECONDS = 30
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_CHALLENGE_TTL_SECONDS = 10 * 60

_UUID_RE = re.compile(
    r"(?i)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})"
)
_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_LOCK = threading.RLock()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _error(message: str, *, stage: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "error": message}
    if stage:
        result["stage"] = stage
    return result


def _normalize_page_id(raw: Any) -> str | None:
    """Accept a UUID or a Notion URL, and return a dashed UUID."""
    if not isinstance(raw, str) or not raw.strip():
        return None

    value = raw.strip()
    if value.startswith(("https://", "http://")):
        path = urlparse(value).path
        matches = _UUID_RE.findall(path)
        if not matches:
            return None
        value = matches[-1]

    compact = value.replace("-", "")
    if not re.fullmatch(r"(?i)[0-9a-f]{32}", compact):
        return None

    return (
        f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}-"
        f"{compact[16:20]}-{compact[20:32]}"
    )


def _api_key() -> str | None:
    value = os.environ.get("NOTION_API_KEY", "").strip()
    return value or None


def _decode_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8", "replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"message": "Notion returned a non-JSON response"}
    return decoded if isinstance(decoded, dict) else {"data": decoded}


def _api_request(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> tuple[int | None, dict[str, Any]]:
    """Make one authenticated Notion REST request without exposing credentials."""
    token = _api_key()
    if token is None:
        return None, {
            "error": "NOTION_API_KEY is not configured",
            "hint": (
                "Create a Notion integration token, share the target page with it, "
                "then store it in ~/.hermes/.env."
            ),
        }

    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Accept": "application/json",
        "User-Agent": "hermes-notion-page-tools/0.1.0",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{_API_BASE}{path}",
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return response.status, {"error": "Notion response was too large"}
            return response.status, _decode_body(raw)
    except HTTPError as exc:
        raw = exc.read(_MAX_RESPONSE_BYTES)
        data = _decode_body(raw)
        message = data.get("message")
        if not isinstance(message, str) or not message:
            message = f"Notion API HTTP {exc.code}"
        return exc.code, {"error": message, "code": data.get("code")}
    except (TimeoutError, URLError, OSError) as exc:
        return None, {"error": f"Notion API request failed: {exc}"}


def _page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if not isinstance(prop, dict) or prop.get("type") != "title":
                continue
            title_parts = prop.get("title", [])
            if isinstance(title_parts, list):
                text = "".join(
                    part.get("plain_text", "")
                    for part in title_parts
                    if isinstance(part, dict)
                ).strip()
                if text:
                    return text
    return "(senza titolo)"


def _in_trash(page: dict[str, Any]) -> bool | None:
    if "in_trash" in page:
        return bool(page["in_trash"])
    # Compatibility with older Notion API responses.
    if "archived" in page:
        return bool(page["archived"])
    return None


def _metadata(page: dict[str, Any], page_id: str) -> dict[str, Any]:
    return {
        "page_id": page.get("id", page_id),
        "title": _page_title(page),
        "url": page.get("url"),
        "parent": page.get("parent"),
        "in_trash": _in_trash(page),
        "last_edited_time": page.get("last_edited_time"),
    }


def _cleanup_challenges() -> None:
    now = time.time()
    expired = [
        token
        for token, item in _PENDING.items()
        if item.get("expires_at", 0) <= now
    ]
    for token in expired:
        _PENDING.pop(token, None)


def _make_challenge(action: str, page_id: str, metadata: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(18)
    with _PENDING_LOCK:
        _cleanup_challenges()
        _PENDING[token] = {
            "action": action,
            "page_id": page_id,
            "title": metadata["title"],
            "expires_at": time.time() + _CHALLENGE_TTL_SECONDS,
        }
    return token


def _read_page(page_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    status, data = _api_request("GET", f"/pages/{page_id}")
    if status is None or status >= 400 or "error" in data:
        return None, _error(
            str(data.get("error", "Unable to read the Notion page")),
            stage="read",
        )
    if not isinstance(data.get("id"), str):
        return None, _error("Notion returned an invalid page response", stage="read")
    return data, None


def _preview_or_execute(
    args: dict[str, Any], *, action: str, desired_in_trash: bool
) -> dict[str, Any]:
    page_id = _normalize_page_id(args.get("page_id"))
    if page_id is None:
        return _error(
            "page_id must be a Notion page UUID or a Notion page URL",
            stage="validation",
        )

    confirmation_token = args.get("confirmation_token")
    if confirmation_token is None or not str(confirmation_token).strip():
        page, failure = _read_page(page_id)
        if failure:
            return failure
        assert page is not None
        metadata = _metadata(page, page_id)
        current = metadata["in_trash"]
        if current is None:
            return _error(
                "Notion response did not expose the page trash state",
                stage="read",
            )
        if current == desired_in_trash:
            return {
                "success": True,
                "action": action,
                "changed": False,
                "verified": True,
                "page": metadata,
                "message": "Nessuna modifica: la pagina è già nello stato richiesto.",
            }

        token = _make_challenge(action, page_id, metadata)
        return {
            "success": True,
            "requires_confirmation": True,
            "action": action,
            "page": metadata,
            "confirmation_token": token,
            "confirmation_expires_in_seconds": _CHALLENGE_TTL_SECONDS,
            "message": (
                "Anteprima pronta. Chiedi conferma esplicita dell'utente per questa "
                "pagina; usa poi lo stesso confirmation_token, senza inventarlo."
            ),
        }

    token = str(confirmation_token).strip()
    with _PENDING_LOCK:
        _cleanup_challenges()
        challenge = _PENDING.get(token)

    if not challenge:
        return _error(
            "confirmation_token mancante, scaduto o già usato; esegui una nuova anteprima",
            stage="confirmation",
        )
    if challenge["action"] != action or challenge["page_id"] != page_id:
        return _error(
            "confirmation_token non corrisponde alla pagina o all'azione richiesta",
            stage="confirmation",
        )

    expected_title = args.get("expected_title")
    if expected_title is not None and str(expected_title) != challenge["title"]:
        return _error(
            "expected_title non corrisponde al titolo letto durante l'anteprima",
            stage="confirmation",
        )

    # Always re-read immediately before the external write.
    page, failure = _read_page(page_id)
    if failure:
        return failure
    assert page is not None
    metadata_before = _metadata(page, page_id)
    current = metadata_before["in_trash"]
    if current is None:
        return _error(
            "Notion response did not expose the page trash state",
            stage="read_before_write",
        )
    if metadata_before["title"] != challenge["title"]:
        return _error(
            "Il titolo della pagina è cambiato dall'anteprima; richiedi una nuova conferma",
            stage="stale_confirmation",
        )
    if current == desired_in_trash:
        with _PENDING_LOCK:
            _PENDING.pop(token, None)
        return {
            "success": True,
            "action": action,
            "changed": False,
            "verified": True,
            "page": metadata_before,
            "message": "Nessuna modifica: la pagina era già nello stato richiesto.",
        }

    status, response = _api_request(
        "PATCH",
        f"/pages/{page_id}",
        {"in_trash": desired_in_trash},
    )
    with _PENDING_LOCK:
        _PENDING.pop(token, None)
    if status is None or status >= 400 or "error" in response:
        return _error(
            str(response.get("error", "Notion rejected the page update")),
            stage="write",
        )

    # Verify the exact target, not merely the PATCH acknowledgement.
    page_after, failure = _read_page(page_id)
    if failure:
        return {
            "success": False,
            "action": action,
            "changed": True,
            "verified": False,
            "page": metadata_before,
            "error": "La modifica è stata accettata, ma la verifica di lettura è fallita.",
            "verification": failure,
            "stage": "verify",
        }
    assert page_after is not None
    metadata_after = _metadata(page_after, page_id)
    verified = metadata_after["in_trash"] == desired_in_trash
    return {
        "success": verified,
        "action": action,
        "changed": True,
        "verified": verified,
        "page": metadata_after,
        "message": (
            "Pagina spostata nel cestino e verificata."
            if desired_in_trash and verified
            else "Pagina ripristinata e verificata."
            if verified
            else "Lo stato restituito da Notion non coincide con quello richiesto."
        ),
        **({} if verified else {"stage": "verify"}),
    }


def _safe_call(args: Any, *, action: str, desired_in_trash: bool) -> str:
    if not isinstance(args, dict):
        return _json(_error("Tool arguments must be an object", stage="validation"))
    try:
        return _json(
            _preview_or_execute(
                args,
                action=action,
                desired_in_trash=desired_in_trash,
            )
        )
    except Exception as exc:  # Handlers must never raise into the agent loop.
        return _json(_error(f"Unexpected plugin error: {exc}", stage="internal"))


def trash_page(args: dict[str, Any], **kwargs: Any) -> str:
    """Preview or move one page to the Notion trash."""
    del kwargs
    return _safe_call(args, action="trash", desired_in_trash=True)


def restore_page(args: dict[str, Any], **kwargs: Any) -> str:
    """Preview or restore one page from the Notion trash."""
    del kwargs
    return _safe_call(args, action="restore", desired_in_trash=False)
