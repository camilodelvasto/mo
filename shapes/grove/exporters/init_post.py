"""Generate self-documenting frontmatter templates for grove posts.

Adapter for: mo grove init <path>
Single file:  mo grove init content/website/en/posts/my-post.md
Directory:    mo grove init content/website/en/
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import yaml


def _title_from_filename(filename: str) -> str:
    """Derive a human title from a markdown filename.

    my-new-post.md -> My New Post
    """
    stem = filename.removesuffix(".md")
    return stem.replace("-", " ").replace("_", " ").title()


def generate_frontmatter(
    *,
    filename: str,
    today: date,
    sections: list[str],
    layouts: list[str],
    lang: str,
) -> str:
    """Generate a complete frontmatter template with commented optional fields.

    sections: discovered from grove directory structure (may be empty).
    layouts: read from shape's layouts module.
    lang: from grove.yaml.
    """
    title = _title_from_filename(filename)
    date_str = today.isoformat()

    if sections:
        section_line = f"# section: \"\"                 # {' | '.join(sections)}"
    else:
        section_line = '# section: ""'

    if not layouts:
        raise ValueError("layouts must not be empty — read them from the shape's layouts module")
    layout_default = layouts[0]
    if len(layouts) > 1:
        layout_line = f"# layout: {layout_default}             # {' | '.join(layouts)}"
    else:
        layout_line = f"# layout: {layout_default}"

    lines = [
        "---",
        f'title: "{title}"          # derived from filename, edit this',
        "published: true               # set to false to unpublish",
        "",
        f"# slug: {filename.removesuffix('.md')}           # defaults to file path if omitted",
        f"publish_date: {date_str}",
        f'excerpt: "{title}"           # shown in index cards and RSS',
        "",
        "# card:",
        '#   image: ""                 # thumbnail; relative to the declared assets/ root',
        '#   bg: ""                    # background color override',
        '#   color: ""                 # text color override',
        '#   hover: ""                 # text hover color override',
        "",
        f"{section_line}",
        "# tags: []                    # e.g. [moui, local-first]",
        "# sticky: false               # pin to top of index listing",
        "# featured: false             # surface in featured slots in grid view",
        "# weight: 0                   # explicit ordering within section; 0 = use date",
        "",
        f"{layout_line}",
        '# theme: ""                   # overrides grove theme for this post only',
        "",
        f"# lang: {lang}                    # inherits grove default if omitted",
        "# translations:",
        "#   de: /path/to/german-version/",
        "",
        "# og:",
        '#   title: ""                 # defaults to post title',
        '#   description: ""           # defaults to excerpt',
        '#   image: ""                # absent → grove default og image → build warning',
        "#   type: article             # article | website",
        "",
        "# related: auto               # auto = computed same-section recency; [slug, slug] = explicit; absent = none",
        "---",
        "",
    ]
    return "\n".join(lines)


def discover_sections(grove_root: Path) -> list[str]:
    """List section names from subdirectories under posts/."""
    posts_dir = grove_root / "posts"
    if not posts_dir.is_dir():
        raise FileNotFoundError(f"No posts/ directory in {grove_root}")
    return sorted(d.name for d in posts_dir.iterdir() if d.is_dir())


def discover_layouts(shape_path: Path) -> list[str]:
    """Read available layout names from the grove shape's layouts module."""
    layouts_file = shape_path / "exporters" / "layouts.py"
    if not layouts_file.exists():
        raise FileNotFoundError(f"No layouts module at {layouts_file}")

    spec = importlib.util.spec_from_file_location("grove_layouts", layouts_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.LAYOUTS.keys())


def has_frontmatter(text: str) -> bool:
    """Check if text starts with valid YAML frontmatter delimiters."""
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    return len(parts) >= 3


def init_file(
    *,
    path: Path,
    today: date,
    sections: list[str],
    layouts: list[str],
    lang: str,
) -> bool:
    """Add frontmatter template to a markdown file if missing.

    Returns True if the file was modified, False if skipped.
    """
    text = path.read_text(encoding="utf-8")
    if has_frontmatter(text):
        return False

    frontmatter = generate_frontmatter(
        filename=path.name,
        today=today,
        sections=sections,
        layouts=layouts,
        lang=lang,
    )

    path.write_text(frontmatter + text, encoding="utf-8")
    return True


def _find_grove_root(path: Path) -> Path:
    """Walk up from path to find the directory containing grove.yaml."""
    candidate = path if path.is_dir() else path.parent
    while candidate != candidate.parent:
        if (candidate / "grove.yaml").exists():
            return candidate
        candidate = candidate.parent
    raise FileNotFoundError(f"No grove.yaml found above {path}")


def _load_grove_lang(grove_root: Path) -> str:
    """Read lang from grove.yaml."""
    grove_yaml = grove_root / "grove.yaml"
    config = yaml.safe_load(grove_yaml.read_text())
    if "lang" not in config:
        raise KeyError(f"No 'lang' field in {grove_yaml}")
    return config["lang"]


def run(corpus_root: Path, instance: str, args: list) -> None:
    if not args:
        print(f"Usage: mo {instance} init <path>")
        print()
        print("  <path> can be a .md file or a grove directory.")
        print("  File:      adds frontmatter template if missing.")
        print("  Directory: batch-initializes all .md files missing frontmatter.")
        sys.exit(1)

    target = Path(args[0]).resolve()
    grove_root = _find_grove_root(target)

    lang = _load_grove_lang(grove_root)
    shape_path = corpus_root / "shapes" / instance
    sections = discover_sections(grove_root)
    layouts = discover_layouts(shape_path)
    today = date.today()

    from cli.output import header, detail, success, note, done

    if target.is_dir():
        posts_dir = grove_root / "posts"
        if not posts_dir.is_dir():
            print(f"No posts/ directory in {grove_root}")
            sys.exit(1)

        md_files = sorted(posts_dir.rglob("*.md"))
        if not md_files:
            print(f"No .md files found under {posts_dir}")
            sys.exit(1)

        header("Initializing:", str(grove_root.relative_to(corpus_root)))
        initialized = 0
        skipped = 0
        for md in md_files:
            changed = init_file(
                path=md,
                today=today,
                sections=sections,
                layouts=layouts,
                lang=lang,
            )
            rel = md.relative_to(grove_root)
            if changed:
                detail("init", str(rel))
                initialized += 1
            else:
                detail("skip", str(rel))
                skipped += 1

        success(f"{initialized} initialized, {skipped} skipped")
        done()
    else:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            frontmatter = generate_frontmatter(
                filename=target.name,
                today=today,
                sections=sections,
                layouts=layouts,
                lang=lang,
            )
            target.write_text(frontmatter, encoding="utf-8")
            header("Created:", str(target.relative_to(corpus_root)))
            done()
            return

        if not target.suffix == ".md":
            print(f"Not a markdown file: {target}")
            sys.exit(1)

        changed = init_file(
            path=target,
            today=today,
            sections=sections,
            layouts=layouts,
            lang=lang,
        )
        if changed:
            header("Initialized:", str(target.relative_to(corpus_root)))
        else:
            note(f"Already has frontmatter: {target.relative_to(corpus_root)}")
        done()
