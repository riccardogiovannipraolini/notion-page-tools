"""Personal Hermes tools for reversible Notion page deletion."""

from . import schemas, tools


def register(ctx):
    """Register the safe trash/restore tools with Hermes."""
    ctx.register_tool(
        name="notion_trash_page",
        toolset="notion_page_tools",
        schema=schemas.TRASH_PAGE,
        handler=tools.trash_page,
    )
    ctx.register_tool(
        name="notion_restore_page",
        toolset="notion_page_tools",
        schema=schemas.RESTORE_PAGE,
        handler=tools.restore_page,
    )
