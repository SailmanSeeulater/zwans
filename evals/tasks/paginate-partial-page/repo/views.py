"""Render a page of search results as plain text."""

from pager import PageNotFound, paginate


def render_results(results: list[str], page: int, per_page: int = 20) -> str:
    try:
        current = paginate(results, page, per_page)
    except PageNotFound:
        return "Page not found."
    lines = [f"- {title}" for title in current.items] or ["No results."]
    nav = []
    if current.has_previous:
        nav.append(f"< page {current.number - 1}")
    nav.append(f"Page {current.number} of {current.total_pages}")
    if current.has_next:
        nav.append(f"page {current.number + 1} >")
    return "\n".join([*lines, "", " | ".join(nav)])
