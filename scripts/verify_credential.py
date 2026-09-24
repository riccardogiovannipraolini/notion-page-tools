"""Read-only health check for the notion-page-tools credential.

Never prints the token. Exercises the plugin's own HTTP layer against the real
Notion API using a GET only -- no writes, no page changes, no confirmation
tokens minted.

Usage:
    python ~/.hermes/plugins/notion-page-tools/scripts/verify_credential.py [PAGE_ID]
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = pathlib.Path.home() / ".hermes" / ".env"


def load_key_from_env_file() -> str | None:
    """Read NOTION_API_KEY from the Hermes .env when the process lacks it."""
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("NOTION_API_KEY="):
            value = stripped.split("=", 1)[1].strip().strip("'\"")
            return value or None
    return None


def describe(secret: str) -> str:
    """Describe a credential without disclosing it."""
    prefix = "ntn_" if secret.startswith("ntn_") else (
        "secret_" if secret.startswith("secret_") else "(prefisso inatteso)"
    )
    return f"prefisso={prefix} lunghezza={len(secret)}"


def main() -> int:
    from_process = bool(os.environ.get("NOTION_API_KEY", "").strip())
    key = os.environ.get("NOTION_API_KEY", "").strip() or load_key_from_env_file()

    print(f"chiave nel file .env : {'si' if load_key_from_env_file() else 'NO'}")
    print(f"chiave nel processo  : {'si' if from_process else 'no (serve riavvio)'}")

    if not key:
        print("\nESITO: nessuna chiave trovata.")
        return 2

    print(f"forma della chiave   : {describe(key)}")

    os.environ["NOTION_API_KEY"] = key
    spec = importlib.util.spec_from_file_location(
        "notion_page_tools_tools", PLUGIN_DIR / "tools.py"
    )
    tools = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(tools)

    status, data = tools._api_request("GET", "/users/me")
    print(f"\nGET /v1/users/me     : HTTP {status}")
    if status != 200:
        print(f"ESITO: autenticazione FALLITA -> {data.get('error')}")
        return 1
    print(f"identita             : {data.get('name')} ({data.get('type')})")

    page_id = sys.argv[1] if len(sys.argv) > 1 else None
    if page_id:
        normalized = tools._normalize_page_id(page_id)
        if not normalized:
            print(f"\nID pagina non valido: {page_id}")
            return 1
        page, failure = tools._read_page(normalized)
        if failure:
            print(f"\nLettura pagina FALLITA -> {failure.get('error')}")
            return 1
        meta = tools._metadata(page, normalized)
        print("\nlettura pagina reale attraverso il plugin (solo GET):")
        print(f"  titolo   : {meta['title']}")
        print(f"  in_trash : {meta['in_trash']}")
        print(f"  url      : {meta['url']}")

    print("\nESITO: credenziale VALIDA. Nessuna scrittura effettuata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
