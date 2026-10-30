# cli/

**Layer:** Infrastructure — Python

Terminal shell for moui. Parses commands, enforces capability declarations, routes to shape handlers. This is a peer shell to the future Tauri application — same kernel contract, same data model, different runtime.

## What belongs here

- `moui.py` — entry point, command dispatch
- `loader.py` — reads moui.json, resolves shape instance paths
- `check.py` — corpus validation
- `ipc.py` — inter-shape message routing
- `store/` — filesystem and SQLite operations

## What does not belong here

- Shape rendering logic — that lives in `shapes/<instance>/renderer/`
- Direct imports from `shapes/` — the CLI reads manifests, it does not import shape code

## Contract

Each module here has a counterpart in `src-tauri/src/`. The contract is the same; the implementation language differs.

## Validation

Run `moui check` to validate the corpus. Run `python3 -m pytest tests/` to test CLI modules.
