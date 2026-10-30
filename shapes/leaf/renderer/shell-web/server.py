"""Leaf HTTP server — STATUS: scaffold.

Only the theme resolver is implemented. The server loop, SSE watchers,
and route handlers will be added in a future pass together with the
renderer implementation. This module re-exports the shared resolver
so the theme resolution contract is callable before the renderer is built.
"""
from cli.resolver import resolve_theme_dir


__all__ = ["resolve_theme_dir"]
