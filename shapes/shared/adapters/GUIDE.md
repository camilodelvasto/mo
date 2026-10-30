# adapters/

Deploy targets. Each adapter implements the same contract:

```python
def deploy(dist_path: Path, config: dict, publish_path: str, *, force: bool = False, spa: bool = False) -> Live | Staged:
def unpublish(config: dict, publish_path: str) -> None:
REQUIRES = ()   # capability names the deploy rail builds and injects into config
```

`deploy()` returns an outcome from `outcome.py`: `Live(url)` when the URL serves the release, `Staged(url, reason)` when the release is on the remote but not served yet. The rail prints `STAGED (not live): <reason>` for a staged deploy and throws on any other return value. `spa` asks for unknown paths to fall back to `index.html`.

The rail (`cli/commands/deploy.py` `_adapter_capabilities`) injects each capability named in `REQUIRES` — `dns`, `declared_mounts` (`{publish_path: [(remote_id, target_file)]}` for every env on any remote declaring the domain), `remote_id` (the deploying remote) — so an adapter never imports a provider or reads targets. `REQUIRES = ()` means the adapter needs none. An adapter without `REQUIRES`, or naming an unknown capability, fails the deploy.

Git-based adapters (codeberg, github) use `shapes/shared/git_pages.py` for the mechanical git primitives: `clone_and_merge`, `clone_and_remove`, `push`. Multiple shapes can coexist on the same pages branch without destroying each other. Platform-specific logic — URL derivation, custom-domain file conventions, error subclasses — lives in each adapter, never in shared code.

- `hetzner.py` — Hetzner box (primary): release + Caddy site + DNS
- `codeberg_pages.py` — Codeberg Pages
- `s3.py` — S3-compatible storage
- `github_pages.py` — GitHub Pages

`git_sync.py` is a sync transport (a `cli/sync` `Transport` over git), not a deploy adapter: it has no `deploy()`/`unpublish()` contract and declares no `REQUIRES`. `outcome.py` is the return contract, not an adapter.
