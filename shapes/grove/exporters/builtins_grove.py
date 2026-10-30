"""Built-in content elements. Each handler returns an HTML fragment — the same contract an
authored element emits — so built-ins and authored elements are interchangeable in a
page body. The registry is declared (name -> handler); adding a built-in is one entry.

Chrome (header/footer) is the shell's responsibility, not a body element. Built-ins are
content elements only. A page body listing "header" or "footer" resolves to an authored
element lookup and throws ResolveError if none exists — intentional.
"""
from components import render_card, format_date


def _grid(config: dict, grove: dict, ctx: dict, *, posts) -> str:
    limit = (config or {}).get("limit")
    items = posts[:limit] if limit is not None else posts
    date_fmt = grove.get("date_format")
    base_path = ctx["base_path"]
    enriched = [
        {**p,
         "publish_date_display": format_date(str(p.get("publish_date") or ""), date_fmt),
         "_thumbnail": (p.get("card") or {}).get("image", "")}
        for p in items
    ]
    cards = "\n".join(
        f"        {render_card(post, index=i, base_path=base_path)}"
        for i, post in enumerate(enriched)
    )
    return f'<div class="feed-grid">\n{cards}\n        </div>'


BUILTINS = {
    "grid": _grid,
}


def is_builtin(name: str) -> bool:
    return name in BUILTINS
