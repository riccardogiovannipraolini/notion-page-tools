"""Safely replace NOTION_API_KEY in ~/.hermes/.env.

The token is read from an invisible prompt: it never appears in shell history,
in process arguments, or on screen. It is validated against the live Notion API
BEFORE the file is touched, so a bad paste can never land in .env.

Usage:
    python3 ~/.hermes/plugins/notion-page-tools/scripts/set_credential.py
"""

from __future__ import annotations

import getpass
import importlib.util
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = pathlib.Path.home() / ".hermes" / ".env"
KEY = "NOTION_API_KEY"


def load_tools():
    spec = importlib.util.spec_from_file_location(
        "notion_page_tools_tools", PLUGIN_DIR / "tools.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def validate(token: str) -> tuple[bool, str]:
    """Check the token against Notion before writing it anywhere."""
    tools = load_tools()
    previous = os.environ.get(KEY)
    os.environ[KEY] = token
    try:
        status, data = tools._api_request("GET", "/users/me")
    finally:
        if previous is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = previous

    if status != 200:
        return False, f"HTTP {status}: {data.get('error')}"

    name = data.get("name")
    kind = data.get("type")
    owner = data.get("bot", {}).get("owner", {}) if isinstance(data.get("bot"), dict) else {}
    owner_type = owner.get("type") if isinstance(owner, dict) else None
    detail = f"{name} (type={kind}"
    if owner_type:
        detail += f", owner={owner_type}"
    detail += ")"
    return True, detail


def write_env(token: str) -> None:
    """Replace the existing key line in place, atomically, preserving mode."""
    original = ENV_FILE.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    replaced = False
    out = []
    for line in lines:
        if line.strip().startswith(f"{KEY}="):
            if replaced:
                continue  # drop any duplicate definitions
            out.append(f"{KEY}={token}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"{KEY}={token}\n")

    backup = ENV_FILE.with_suffix(".env.bak" if ENV_FILE.suffix else ".bak")
    shutil.copy2(ENV_FILE, backup)
    os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)

    fd, tmp_path = tempfile.mkstemp(dir=str(ENV_FILE.parent), prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(out))
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, ENV_FILE)
    except BaseException:
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        raise

    print(f"backup salvato in    : {backup}")


def main() -> int:
    if not ENV_FILE.is_file():
        print(f"File non trovato: {ENV_FILE}")
        return 2

    print("Incolla il PAT di Notion e premi Invio.")
    print("L'input e' invisibile: non compare a schermo ne' nella cronologia.\n")
    token = getpass.getpass("PAT Notion: ").strip().strip("'\"")

    if not token:
        print("\nNessun valore inserito. Niente e' stato modificato.")
        return 2
    if not token.startswith(("ntn_", "secret_")):
        print("\nIl valore non sembra un token Notion (atteso prefisso 'ntn_').")
        print("Niente e' stato modificato.")
        return 2

    print("\nverifico il token con Notion prima di scrivere...")
    ok, detail = validate(token)
    if not ok:
        print(f"TOKEN RIFIUTATO -> {detail}")
        print("Il file .env NON e' stato modificato.")
        return 1

    print(f"token valido         : {detail}")
    write_env(token)
    print(f"scritto in           : {ENV_FILE}")
    print("\nFatto. Riavvia Hermes perche' la nuova chiave venga caricata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
