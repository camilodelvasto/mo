"""Build-time CSS scoping for authored elements (Vue/Astro-style).

scope_css rewrites each selector with `[data-<token>]`; the composer stamps the same
`data-<token>` attribute on the element's root node. Theme tokens are custom properties
on :root and pierce scoping untouched. @keyframes/@font-face preludes are left alone;
@media/@supports content is recursed into.
"""
import hashlib
import tinycss2

_NESTING_AT_RULES = {"media", "supports", "container", "layer"}

# Selectors that must not be prefixed — they are document-level, not element-level.
_UNSCOPED_SELECTORS = {":root", "html", "body"}


def scope_token(element_name: str, salt: str) -> str:
    """Short, stable, collision-resistant scope id for an element."""
    digest = hashlib.sha256(f"{element_name}\0{salt}".encode("utf-8")).hexdigest()
    return "p-" + digest[:8]


def _split_top_level_comma_groups(prelude_tokens: list) -> list[list]:
    """Split a prelude's component-value list on top-level commas only.

    tinycss2 wraps :is(...) as a function block and [...] as a [] block —
    both are single tokens, so commas inside them are NOT top-level and
    are not split here.
    """
    groups: list[list] = []
    current: list = []
    for tok in prelude_tokens:
        if tok.type == "literal" and tok.value == ",":
            groups.append(current)
            current = []
        else:
            current.append(tok)
    groups.append(current)
    return groups


def _scope_prelude(prelude_tokens: list, attr: str) -> list:
    """Prefix each comma-separated selector group in a qualified-rule prelude with [attr].

    Groups that are exactly :root, html, or body are emitted unchanged.
    Splitting is done on top-level commas only — commas inside :is()/[attr] are preserved.
    """
    groups = _split_top_level_comma_groups(prelude_tokens)
    scoped_parts = []
    for group in groups:
        text = tinycss2.serialize(group).strip()
        if not text:
            continue
        if text in _UNSCOPED_SELECTORS:
            scoped_parts.append(text)
        else:
            scoped_parts.append(f"[{attr}] {text}")
    scoped = ", ".join(scoped_parts)
    return tinycss2.parse_component_value_list(" " + scoped + " ")


def _scope_rules(rules: list, attr: str) -> list:
    out = []
    for node in rules:
        if node.type == "qualified-rule":
            node.prelude = _scope_prelude(node.prelude, attr)
            out.append(node)
        elif node.type == "at-rule":
            name = node.lower_at_keyword or ""
            if name in _NESTING_AT_RULES and node.content is not None:
                inner = tinycss2.parse_rule_list(node.content)
                node.content = tinycss2.parse_component_value_list(
                    tinycss2.serialize(_scope_rules(inner, attr))
                )
            out.append(node)
        else:
            out.append(node)
    return out


def scope_css(css: str, token: str) -> str:
    """Return css with every selector scoped under [data-<token>]."""
    attr = f"data-{token}"
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    return tinycss2.serialize(_scope_rules(rules, attr)).strip()
