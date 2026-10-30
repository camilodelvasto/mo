"""Component resolution — corpus-root-first, then shape-specific.

Same precedence pattern as theme resolution (resolver.py).
"""
from pathlib import Path


def resolve_component(
    name: str,
    *,
    corpus_root: Path,
    shape_path: Path,
) -> Path:
    """Resolve a component directory via corpus root -> shape-specific chain.

    Args:
        name: component name like 'stat-card'
        corpus_root: path to the corpus root
        shape_path: path to the shape root (shapes/deck/)

    Returns:
        Path to the resolved component directory.

    Raises:
        FileNotFoundError if neither location has the component.
    """
    corpus_dir = corpus_root / "components" / name
    if corpus_dir.is_dir():
        if not (corpus_dir / "component.yaml").exists():
            raise FileNotFoundError(
                f"Component directory exists but missing component.yaml: {corpus_dir}"
            )
        return corpus_dir

    shape_dir = shape_path / "components" / name
    if shape_dir.is_dir():
        if not (shape_dir / "component.yaml").exists():
            raise FileNotFoundError(
                f"Component directory exists but missing component.yaml: {shape_dir}"
            )
        return shape_dir

    raise FileNotFoundError(
        f"Component not found: '{name}' "
        f"(checked {corpus_dir} and {shape_dir})"
    )


def collect_component_refs(content_data: dict) -> set:
    """Walk slides and collect all component references."""
    refs = set()
    for slide in content_data.get("slides", []):
        content = slide.get("content", {})
        if isinstance(content, dict) and content.get("component"):
            refs.add(content["component"])
        for side in ("left", "right"):
            side_data = slide.get(side, {})
            if isinstance(side_data, dict):
                sc = side_data.get("content", {})
                if isinstance(sc, dict) and sc.get("component"):
                    refs.add(sc["component"])
        for cell in slide.get("cells", []):
            cc = cell.get("content", {})
            if isinstance(cc, dict) and cc.get("component"):
                refs.add(cc["component"])
    return refs
