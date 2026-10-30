"""Shared theme directory resolution — path-based, no fallback chains.

The theme field in content YAML is a relative path from the content file
to the theme directory. The resolver follows the path. If it doesn't
exist, it throws.
"""
from pathlib import Path


def resolve_theme_dir(theme_ref: str, content_path: Path) -> Path:
    """Resolve a theme directory from a path relative to the content file.

    Args:
        theme_ref: relative path from the YAML (e.g. 'themes/pitch')
        content_path: path to the content YAML file

    Returns:
        Resolved absolute path to the theme directory.

    Raises:
        FileNotFoundError if the directory doesn't exist.
    """
    theme_dir = (content_path.parent / theme_ref).resolve()
    if not theme_dir.is_dir():
        raise FileNotFoundError(
            f"Theme directory not found: {theme_dir} "
            f"(resolved from '{theme_ref}' relative to {content_path.parent})"
        )
    return theme_dir
