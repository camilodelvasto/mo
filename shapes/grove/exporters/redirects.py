"""Grove redirects generator — Netlify and Caddy redirect formats."""


def _normalize_path(path: str) -> str:
    """Normalize a path to /path/ format."""
    path = path.strip("/")
    return f"/{path}/"


def generate_redirects_file(posts: list[dict]) -> str:
    """Generate Netlify/Codeberg format redirects: /old-path/ /new-path/ 301"""
    lines = []
    for post in posts:
        target = post["url_path"]
        for old in post.get("redirects", []):
            source = _normalize_path(old)
            lines.append(f"{source} {target} 301")
    return "\n".join(lines)


def generate_caddy_redirects(posts: list[dict]) -> str:
    """Generate Caddy format redirects: redir /old-path/ /new-path/ 301"""
    lines = []
    for post in posts:
        target = post["url_path"]
        for old in post.get("redirects", []):
            source = _normalize_path(old)
            lines.append(f"redir {source} {target} 301")
    return "\n".join(lines)
