from inspect import signature


def rich_keyword(method) -> str:
    """Rich-content argument name used by the installed Pyrogram fork.

    Kurigram names it ``rich_message``; wzgram names it ``rich_text``.
    """
    try:
        parameters = signature(method).parameters
    except (TypeError, ValueError):
        return "rich_message"
    return "rich_text" if "rich_text" in parameters else "rich_message"
