"""Reads moui.json and resolves shape instance paths.

The loader is the first thing the CLI touches. It reads moui.json from the
corpus root, validates its structure, and resolves each shape instance to
its directory path and parsed manifest.
"""
import json
from pathlib import Path

import yaml


def load_corpus(corpus_root: Path) -> dict:
    """Read moui.json from corpus_root. Raises FileNotFoundError if missing."""
    moui_path = corpus_root / "moui.json"
    if not moui_path.exists():
        raise FileNotFoundError(f"No moui.json found at {moui_path}")
    return json.loads(moui_path.read_text())


def resolve_shape(corpus: dict, instance_name: str, corpus_root: Path) -> dict:
    """Resolve a single shape instance to its path and parsed manifest.

    Returns a dict with:
        instance_name: str
        shape_name: str (upstream shape name)
        version: str
        path: Path (absolute path to shape directory)
        manifest: dict (parsed shape.manifest.yaml)

    Raises KeyError if instance_name is not in corpus["shapes"].
    Raises FileNotFoundError if the shape directory or manifest is missing.
    """
    if instance_name not in corpus["shapes"]:
        raise KeyError(f"Shape instance '{instance_name}' not found in moui.json")

    shape_entry = corpus["shapes"][instance_name]
    shape_path = (corpus_root / "shapes" / instance_name).resolve()

    if not shape_path.is_dir():
        raise FileNotFoundError(f"Shape directory not found: {shape_path}")

    manifest_path = shape_path / "shape.manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Shape manifest not found: {manifest_path}")

    manifest = yaml.safe_load(manifest_path.read_text())

    return {
        "instance_name": instance_name,
        "shape_name": shape_entry["shape"],
        "version": shape_entry["version"],
        "path": shape_path,
        "manifest": manifest,
    }


def resolve_all_shapes(corpus: dict, corpus_root: Path) -> dict:
    """Resolve all shape instances declared in moui.json.

    Returns a dict keyed by instance name, each value from resolve_shape().
    """
    return {
        name: resolve_shape(corpus, name, corpus_root)
        for name in corpus["shapes"]
    }
