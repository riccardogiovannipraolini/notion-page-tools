"""Model-facing schemas for the Notion page tools."""

_PAGE_ID = {
    "type": "string",
    "description": "Notion page UUID, with or without dashes, or a Notion page URL.",
}
_CONFIRMATION_TOKEN = {
    "type": "string",
    "description": (
        "Only pass the exact confirmation_token returned by an earlier preview "
        "after the user explicitly confirms that exact page and action. Never invent it."
    ),
}
_EXPECTED_TITLE = {
    "type": "string",
    "description": (
        "Optional exact title read during the preview. If supplied and the title changed, "
        "the operation is refused."
    ),
}

TRASH_PAGE = {
    "name": "notion_trash_page",
    "description": (
        "Safely move exactly one Notion page to the Notion trash. This is reversible, "
        "not a permanent deletion. The first call must omit confirmation_token: it only "
        "reads the page and returns a preview plus a one-time token. Ask the user to "
        "explicitly confirm that preview, then call again with the exact token. The tool "
        "reads the page again before writing and verifies in_trash=true afterward."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page_id": _PAGE_ID,
            "confirmation_token": _CONFIRMATION_TOKEN,
            "expected_title": _EXPECTED_TITLE,
        },
        "required": ["page_id"],
        "additionalProperties": False,
    },
}

RESTORE_PAGE = {
    "name": "notion_restore_page",
    "description": (
        "Safely restore exactly one Notion page from the Notion trash. The first call "
        "must omit confirmation_token: it only reads the page and returns a preview plus "
        "a one-time token. Ask the user to explicitly confirm that preview, then call "
        "again with the exact token. The tool reads the page again before writing and "
        "verifies in_trash=false afterward."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page_id": _PAGE_ID,
            "confirmation_token": _CONFIRMATION_TOKEN,
            "expected_title": _EXPECTED_TITLE,
        },
        "required": ["page_id"],
        "additionalProperties": False,
    },
}
