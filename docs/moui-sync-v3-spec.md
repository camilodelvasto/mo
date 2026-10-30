# Moui Sync — v3 Spec

Builds on v2 (the implemented spec). Removes the workspace concept; replaces `workspace.yaml` / `device.yaml` with `infrastructure/syncs/*.yaml` declarations that mirror the existing `infrastructure/targets/` pattern. CLI takes a folder path, same shape as `mo serve` and `mo deploy`. Per-folder git sync, SSH-agent auth and identity, optional age-over-SSH encryption per folder — all carried forward from v2.

---

## Principles

Non-negotiable. Every implementation decision honors them.

- **Adapter-based.** Transport and encryption are interfaces. Selection is by config, never by sniffing.
- **Declarative, nothing inferred.** Every behavior comes from explicit config. Missing config is an error. Defaults exist only for fields with universal values.
- **Throw always, make it loud.** No silent fallbacks. No exception swallowing. Every failure surfaces with a typed error and propagates.
- **No tight coupling.** Watcher does not know about transports. Transports do not know about the watcher. CLI talks to the daemon over a documented socket protocol. Sync code shares no modules with deploy code.
- **No plaintext secrets.** SSH agent is the only key surface. The runtime stores no keys, generates no keys, manages no key material on disk.
- **Nothing hardcoded.** Folder paths, remote names, encryption recipients — all declared by the user.

---

## Git as infrastructure, not as protocol

Git is not an ideal sync protocol. Commit-per-sync produces noisy history. Text-merge does not understand op-log shapes. Two writers editing the same row produce a conflict git cannot resolve semantically. These are real limits, acknowledged.

Git is chosen because it is excellent *infrastructure*. The transport is SSH to a forge. Git provides the consistency model — a content-addressed log any peer can fetch and reconcile. From this we get five things a custom protocol does not give us:

- Authentication via existing SSH agent. No new identity infrastructure.
- Durable storage on infrastructure we don't run. No relays, no buckets, no operational burden.
- A working browse/review UI on every forge. Synced data is inspectable in a web browser without any Moui tooling.
- Conflict detection for free (push refusal when remote is ahead).
- A scriptable escape hatch. When sync goes wrong, the user has a standard tool to fix it.

The trade-off: history is noisy and conflicts on shape-aware files (op-logs) are not auto-merged in v3. Both are addressable later without changing the Transport interface. Squashing strategies and shape-aware reconciliation slot in as layers above the transport, not as transport changes.

---

## Conflict reporting vs. conflict resolution

The Transport detects divergence and reports it via `PullOutcome.conflicts`. It does not resolve.

In v3, the daemon receives the conflict list and surfaces it via status; the user resolves manually with git. In v1, a separate `Reconciler` layer will subscribe to conflict events, examine the conflicting paths, and dispatch to shape-aware merge logic (op-log merge for `ops.jsonl`, Yjs merge for CRDT-backed shapes). The Transport interface does not change. **`PullOutcome.conflicts` is the seam where v1's Reconciler plugs in.**

---

## Model

A synced folder is any folder that has a corresponding declaration in `infrastructure/syncs/`. Each declaration names one folder, one remote, and one encryption setting. The daemon scans `infrastructure/syncs/` recursively, builds a list of folders to watch, and runs sync per folder independently.

There is no workspace concept. There is no bootstrap folder. There is no per-workspace metadata file. The source of truth is the declarations in `infrastructure/syncs/`.

```
~/code/my-moui/
   infrastructure/                       ← itself synced; contains all sync declarations
      .git/
      remotes.yaml                       ← remote registry (existing pattern)
      syncs/
         self.yaml                       ← declares: infrastructure/ syncs to its remote
         content.yaml                    ← declares: content/ syncs to its remote
         content/
            moui.yaml                    ← declares: content/moui/ syncs to its remote
         personal.yaml                   ← declares: personal/ syncs to its remote
      targets/                           ← deploy declarations (existing, unchanged)
   content/                              ← synced folder
      .git/
      moui/                              ← also a synced folder
         .git/
         ...
      ...
   personal/                             ← synced folder
      .git/
      ...
```

**The `syncs/` tree mirrors the content tree.** Same pattern grove already uses for deploys (`targets/`). `content/moui/` is declared by `infrastructure/syncs/content/moui.yaml`.

**The infrastructure folder syncs itself** via `infrastructure/syncs/self.yaml`. This is not a special concept — just one declaration among many that happens to point at the folder containing the declarations. On a new device, cloning `infrastructure/` is the manual bootstrap step that exposes all other declarations to the runtime.

**Synced folders can nest.** `content/` and `content/moui/` can both be declared independently, each with its own remote. This is unusual but supported; the daemon treats each declaration as independent and the user takes responsibility for not creating absurd configurations (committing the same file to two different remotes via overlapping declarations).

---

## Configuration

### `infrastructure/remotes.yaml` (existing, unchanged)

Sync remotes go alongside deploy remotes. The new adapter value is `git_sync`.

```yaml
remotes:
  # existing deploy remote
  codeberg/moui-pages:
    adapter: codeberg_pages
    repo: git@codeberg.org:moui/pages.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent

  # sync remotes
  codeberg/moui-content-sync:
    adapter: git_sync
    repo: git@codeberg.org:example/moui-content.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent

  github/moui-infra-sync:
    adapter: git_sync
    repo: git@github.com:example/moui-infra.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent
```

The adapter is forge-agnostic. The SSH host comes from the `repo` URL.

Remote resolution uses `cli/infra/remotes.py` (the existing loader). The sync code does not invent a parallel resolution path.

### `infrastructure/syncs/<path-mirror>.yaml` (committed, one per synced folder)

```yaml
# infrastructure/syncs/self.yaml
version: 1

target: ..                                # path from syncs/ to the synced folder
remote: github/moui-infra-sync            # ID into remotes.yaml
encryption:
  type: age-ssh                           # none | age-ssh
  recipients:
    - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... laptop"
    - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... work-machine"
sync:                                     # optional per-folder overrides
  debounce_seconds: 30
  max_debounce_seconds: 300
```

```yaml
# infrastructure/syncs/content/moui.yaml
version: 1

target: ../../../content/moui              # path from syncs/ to the synced folder
remote: codeberg/moui-content-sync
encryption:
  type: none
```

**Required fields:** `version`, `target`, `remote`, `encryption.type`.
**Optional fields:** `encryption.recipients` (required when `type: age-ssh`), `sync.debounce_seconds`, `sync.max_debounce_seconds`.

`target` is a relative path from the `syncs/` directory to the folder being synced. The convention is path-mirroring — `infrastructure/syncs/content/moui.yaml` has `target: ../../../content/moui` — but the runtime trusts the declared path and does not enforce the mirror. Hand-edited declarations with non-mirror paths work fine.

### `~/.config/moui/sync/state.yaml` (per-device, never committed)

```yaml
version: 1

device:
  id: 01HK8QZ2N3X4Y5T6V7W8R9P0M2          # ULID, generated on first daemon start
  display_name: "alex's laptop"

# per-folder local overrides, keyed by absolute path
overrides:
  ~/code/my-moui/content/moui:
    debounce_seconds: 60                  # this device prefers slower commits
```

Per-device only. Holds this device's ID, display name, and any local-only overrides. Never travels with the workspace. Lives in the standard user config directory (XDG on Linux, `~/Library/Application Support/moui/sync/state.yaml` on macOS).

### Validation

- Missing required field → `ConfigValidationError`
- Unknown top-level field → `ConfigValidationError` (`pydantic` strict + `extra="forbid"`)
- `remote` references an ID absent from `remotes.yaml` → `RemoteNotFoundError`
- `recipients` entries not valid SSH public keys → `InvalidRecipientError`
- `target` path doesn't exist on disk → `TargetMissingError` at daemon startup (each tracked folder must exist; missing ones surface loudly)
- `version` mismatch → `UnsupportedVersionError`

### Sync timing defaults

Workspace-level defaults are constants in code, not declared:

- `debounce_seconds`: 10
- `max_debounce_seconds`: 60

Per-folder declarations override these. There is no intermediate "workspace defaults" file — if you want different defaults across multiple folders, set them per-folder.

---

## Components

```
   CLI (mo sync …, mo sheets serve, mo grove serve, etc.)
            │
            │ JSON-RPC over Unix socket
            ▼
   moui-sync daemon
      ├─ Lock                    (~/.config/moui/sync/pid + flock)
      ├─ Discovery               (scans infrastructure/syncs/ at startup)
      ├─ Watcher pool            (one per tracked folder)
      ├─ Scheduler               (per-folder debounced sync)
      ├─ EventBroadcaster
      ├─ LogWriter               (~/.config/moui/sync/sync.log JSONL + rotation)
      └─ Per-folder Transport stack
            ├─ adapter: GitSyncAdapter
            └─ wrapper: EncryptionLayer (none | age-ssh)
```

---

## Discovery

The daemon takes one CLI argument: `--infrastructure <path>`, pointing at the infrastructure folder. From there it scans `<path>/syncs/` recursively, reads every `*.yaml` file as a sync declaration, and builds the watched-folder list.

```
moui-sync daemon --infrastructure ~/code/my-moui/infrastructure
```

For each declaration:

1. Validate against the schema.
2. Resolve `remote` via `<path>/remotes.yaml`.
3. Resolve `target` (relative to `syncs/` directory) to an absolute path.
4. Verify the target folder exists. If not → `TargetMissingError`, log it, continue (other folders still work).
5. Build a Transport stack via `build_transport(folder_cfg, remote_cfg)`.
6. Start a watcher and scheduler for the folder.

If `infrastructure/syncs/` doesn't exist or has no declarations, daemon starts but watches nothing. Status reflects this.

Adding a new declaration (file) requires `mo sync rescan` or daemon restart. The daemon does not watch `infrastructure/syncs/` itself for new files — declarations are infrequent, manual reload is appropriate.

---

## Transport interface

```python
from abc import ABC, abstractmethod
from pathlib import Path
from pydantic import BaseModel
from typing import Literal

class SyncOutcome(BaseModel):
    committed_sha: str | None
    pushed: bool
    files_changed: list[Path]

class PullOutcome(BaseModel):
    head: str
    merged_commits: list[str]
    conflicts: list[Path]          # the Reconciler seam (v1)

class RepoStatus(BaseModel):
    state: Literal["clean", "dirty", "ahead", "behind", "diverged", "conflicted", "not_initialized"]
    head: str | None
    uncommitted: list[Path] = []
    ahead: int = 0
    behind: int = 0
    conflicts: list[Path] = []

class Transport(ABC):
    @abstractmethod
    def initialize(self, folder: Path, remote_config: dict) -> None: ...

    @abstractmethod
    def sync(self, folder: Path) -> SyncOutcome: ...

    @abstractmethod
    def pull(self, folder: Path) -> PullOutcome: ...

    @abstractmethod
    def status(self, folder: Path) -> RepoStatus: ...
```

`initialize` is the one-time setup: `git init` if needed, configure `user.name`/`user.email`, add remote, set tracking branch. Idempotent.

---

## Composition

```python
def build_transport(folder_cfg: FolderConfig, remote_cfg: dict) -> Transport:
    if remote_cfg["adapter"] != "git_sync":
        raise UnknownAdapterError(remote_cfg["adapter"])
    base: Transport = GitSyncAdapter(remote_cfg)

    match folder_cfg.encryption.type:
        case "none":
            return base
        case "age-ssh":
            recipients = [pyrage.ssh.Recipient.from_str(r) for r in folder_cfg.encryption.recipients]
            return EncryptionWrapper(inner=base, recipients=recipients)
```

Adding a transport or encryption type means editing this function. Composition is visible in one place.

---

## Encryption: age over SSH

When `encryption.type: age-ssh`:

**On commit:** for every plaintext file in the working tree (excluding gitignored paths and `.age` files), the runtime ensures `{path}.age` exists with current ciphertext, encrypted to the declared SSH recipients via `pyrage`. The `.age` files are tracked by git; plaintext is gitignored.

**On pull:** for every `.age` file that arrived or changed, decrypt to its plaintext path. Decryption requests the SSH agent for an Ed25519 key matching one of the recipients. Deleted `.age` files trigger deletion of plaintext counterparts.

**Identity source:** SSH agent (`SSH_AUTH_SOCK`). The runtime stores no private keys.

**Invariant:** for every plaintext file P in the folder (not otherwise gitignored), `P.age` exists and matches the current contents.

```python
import pyrage
from pyrage.ssh import Recipient, Identity

def encrypt_file(plaintext_path: Path, recipients: list[Recipient]) -> None:
    plaintext = plaintext_path.read_bytes()
    ciphertext = pyrage.encrypt(plaintext, recipients)
    (plaintext_path.parent / f"{plaintext_path.name}.age").write_bytes(ciphertext)

def decrypt_file(ciphertext_path: Path, agent_identities: list[Identity]) -> None:
    ciphertext = ciphertext_path.read_bytes()
    plaintext = pyrage.decrypt(ciphertext, agent_identities)
    plaintext_path = ciphertext_path.with_suffix("")
    plaintext_path.write_bytes(plaintext)
```

**Failure modes, all loud:**

- Decryption fails → `DecryptionError(file=..., cause="no matching SSH key in agent")`. Pull aborts.
- Encryption fails → `EncryptionError(file=..., cause=...)`. Commit aborts.
- Recipient malformed → `InvalidRecipientError(value=...)` at config load.
- SSH agent unavailable → `SSHAgentUnavailableError` at daemon startup.

**What leaks to the remote:** filenames, directory structure, file sizes, modification times. File contents are protected.

**No history rekeying.** Removing a recipient stops future commits from being encrypted to them but does not re-encrypt existing history. Documented limitation.

**Ed25519 only in v3.** RSA SSH keys for age are not enabled.

---

## Authentication

All git operations rely on SSH agent. The runtime invokes git with:

```
GIT_TERMINAL_PROMPT=0
SSH_AUTH_SOCK=<inherited>
```

If git prompts for credentials, it fails immediately. No password handling, no token storage, no HTTPS auth.

`mo sync init` verifies SSH access to the chosen remote before writing the declaration:

```
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@<host>
```

Non-zero exit (other than the host's standard "auth ok, no shell" message) → `SSHAccessError`.

---

## Watcher

One `watchdog` watcher per tracked folder. On any filesystem event in that folder (excluding ignored paths), the per-folder scheduler is poked. Each folder has its own debounce timer.

**Debounce:** events reset a per-folder timer set to fire `debounce_seconds` ahead. Folder-level override (`sync.debounce_seconds` in the declaration) takes precedence over the workspace-level default.

**Maximum quiet window:** if events have continuously reset the timer for `max_debounce_seconds`, force a sync regardless.

**Ignored paths** (per-folder, written to `<folder>/.gitignore` during init if missing):

```
.DS_Store
*.swp
*~
.#*
state.sqlite
__pycache__/
.rendered/
```

When `encryption.type: age-ssh`, an additional rule gitignores plaintext file extensions found at init time (`*.yaml`, `*.jsonl`, `*.md`, etc.). User must add new extensions explicitly as they introduce them.

---

## Pull policy

- **On daemon startup:** pull each tracked folder once.
- **On `mo sync pull [folder]`:** pull on demand.
- **Never auto-pull before push.** Push failures due to remote-ahead surface as `Diverged`; the user runs `mo sync pull <folder>`.

Op-log-aware merging is deferred to v1 via the Reconciler layer.

---

## CLI

The commands take folder paths as arguments, same shape as `mo serve` and `mo deploy`. No wizards, no workspace concepts. Each command operates on what's in front of it.

```
mo sync init <folder>                            create infrastructure/syncs/<path-mirror>.yaml
mo sync <folder>                                 sync once now (commit + push)
mo sync pull [folder]                            pull (all tracked or one)
mo sync status                                   per-folder state
mo sync status --watch                           live updates (TUI)
mo sync logs                                     print recent sync.log entries
mo sync logs --follow                            follow mode
mo sync rescan                                   re-scan infrastructure/syncs/; pick up new declarations
mo sync recipients <folder> list                 show recipients
mo sync recipients <folder> add <ssh-pubkey>     add recipient, commit, push
mo sync recipients <folder> remove <ssh-pubkey>  remove recipient
mo sync forget <folder>                          remove declaration; leave files alone
mo sync daemon start|stop|restart|status         manage daemon
```

### `mo sync init <folder>`

The folder argument is the target. The flow:

1. Resolve `<folder>` to an absolute path. Verify it exists.
2. Find `infrastructure/` by walking up from `<folder>` until `infrastructure/remotes.yaml` is found, or accept `--infrastructure <path>` explicitly.
3. Compute the declaration path: mirror the relative position. If `<folder>` is `<infra-parent>/content/moui`, the declaration goes at `infrastructure/syncs/content/moui.yaml`. If the folder lives outside the infrastructure parent's tree, error: "the folder must be in the same directory tree as infrastructure/."
4. If the declaration already exists, error: "already configured. Use `mo sync forget` first, or edit the file directly."
5. Prompt for remote (tab-completes from `remotes.yaml`).
6. Prompt for encryption type.
7. For `age-ssh`: prompt for recipient SSH public keys (paste or `.pub` file path). Validate format.
8. Verify SSH access to the chosen remote.
9. For `age-ssh`: verify SSH agent has a matching key (warn loudly if not, but allow init to proceed — the user might be setting up declarations for a device that isn't this one).
10. Write `infrastructure/syncs/<path-mirror>.yaml`.
11. In the target folder: `git init` if not a repo, configure `user.name`/`user.email` from remote config, add remote, write `.gitignore` if missing.
12. Attempt initial pull. Empty remote treated as success.
13. If the daemon is running, send it a `rescan` RPC so it starts watching the new folder immediately.

### `mo sync <folder>`

Force a sync of one folder now, bypassing debounce. Equivalent to telling the daemon to sync that folder immediately.

### Status output

```
DAEMON   running (PID 12345, 2m)
INFRA    ~/code/my-moui/infrastructure   3 declarations

infrastructure        ●  clean    github/moui-infra-sync     (age-ssh, 2 keys)    up to date
content/moui          ●  dirty    codeberg/moui-content-sync (plain)              3 files, commit in 7s
content/personal      ●  clean    codeberg/moui-personal-sync (age-ssh, 1 key)    up to date
```

Folders are shown by their path relative to the infrastructure folder's parent. The infrastructure folder itself shows as `infrastructure`.

---

## Adding a second device

No `--join` command. The flow uses tools the user already knows:

1. `git clone <infrastructure-remote-url> ~/code/my-moui/infrastructure/` — manual clone of the infrastructure folder. This is the bootstrap.
2. `mo sync daemon start --infrastructure ~/code/my-moui/infrastructure/` — daemon discovers declarations.
3. Daemon notices declarations whose target folders don't exist on disk yet. Surfaces them:

```
3 declarations found. 2 target folders are missing:

   content/moui          → codeberg/moui-content-sync
   content/personal      → codeberg/moui-personal-sync

Clone them now? [Y/n]
```

4. User confirms. Daemon clones each via its remote, verifies SSH agent keys for encrypted folders, starts watching.

If the user wants to set up the second device without auto-cloning, `--no-auto-clone` skips step 3 and folders just show as "target missing" in status until manually populated.

---

## Daemon ↔ client protocol

JSON-RPC 2.0 over Unix socket.

- Linux: `$XDG_RUNTIME_DIR/moui-sync.sock`
- macOS: `~/Library/Application Support/moui/sync.sock`

Socket permissions: `0o600`. Owner-only.

**Methods:**

```
status                                           → StatusResponse
sync           { folder: str }                   → SyncOutcome
push           { folder?: str }                  → list[SyncOutcome]
pull           { folder?: str }                  → list[PullOutcome]
rescan                                           → { added: list[str], removed: list[str] }
recipients.list    { folder: str }               → list[str]
recipients.add     { folder: str, pubkey: str }  → { recipients: list[str] }
recipients.remove  { folder: str, pubkey: str }  → { recipients: list[str] }
forget         { folder: str }                   → { ok: true }
subscribe      { stream: "events", folder?: str }  → streaming response
ping                                             → { ok: true, version, uptime_seconds }
```

Every request and response carries `version: 1`. Unknown method or version mismatch → typed JSON-RPC error envelope.

**Events stream** (all events are folder-scoped):

```json
{ "type": "sync.started",     "folder": "content/moui", "ts": "..." }
{ "type": "sync.encrypted",   "folder": "infrastructure", "files": 3, "ts": "..." }
{ "type": "sync.committed",   "folder": "content/moui", "sha": "abc123", "files": 3, "ts": "..." }
{ "type": "sync.pushed",      "folder": "content/moui", "ts": "..." }
{ "type": "sync.error",       "folder": "content/moui", "error_class": "PushFailedError", "detail": "...", "ts": "..." }
{ "type": "pull.started",     "folder": "content/moui", "ts": "..." }
{ "type": "pull.decrypted",   "folder": "infrastructure", "files": 5, "ts": "..." }
{ "type": "pull.completed",   "folder": "content/moui", "head": "def456", "ts": "..." }
{ "type": "watch.changed",    "folder": "content/moui", "paths": ["..."], "ts": "..." }
```

Subscribers may pass a `folder` filter to receive only events for a specific tracked folder.

Folder paths in events are the absolute paths on disk; clients can map to display names by stripping the infrastructure-parent prefix.

---

## Renderer integration — shape-agnostic

Sync status integration is a **cross-shape pattern**. Any shape's `serve` command may subscribe to the daemon and surface sync state in its UI.

The integration surface is the JSON-RPC client at `cli/sync/client.py`. Each shape's serve imports it, subscribes to events filtered by its folder, and forwards them via its existing UI channel.

For v3, sheets is the demonstration. Grove and deck integrate the same way when their renderers grow to need it.

UI status pill (shape-agnostic visual contract):

- `synced 3s ago`
- `syncing…`
- `↑ 2 ahead`
- `⚠ diverged — run 'mo sync pull <folder>'`
- `⚠ decrypt error — see logs`
- `sync: offline` (daemon unavailable; renderer continues read-only)
- `not synced` (served path is not in any tracked folder)

---

## Daemon lifecycle

**Linux** — systemd user service:

```ini
# ~/.config/systemd/user/moui-sync.service
[Unit]
Description=Moui Sync Daemon
After=network-online.target

[Service]
ExecStart=%h/.local/bin/moui-sync daemon --infrastructure %h/code/my-moui/infrastructure
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

The infrastructure path is provided at install time. Users with multiple workspaces install separate units with different paths.

**macOS** — launchd agent at `~/Library/LaunchAgents/app.moui.sync.plist` with `RunAtLoad` and `KeepAlive`.

**Windows** — deferred.

**Foreground mode** for development: `moui-sync daemon --infrastructure ./infrastructure --foreground`.

**Single-instance per infrastructure folder:** `~/.config/moui/sync/pid` locked with `flock`. The lock file contains the infrastructure path. A second daemon attempting to start with the same `--infrastructure` argument exits with `WorkspaceLockedError`. Different infrastructure folders can have separate daemons (each with its own lock file path computed from a hash of the infrastructure path).

---

## Sync log: `~/.config/moui/sync/sync.log`

Append-only JSON Lines, same schema as events stream. Rotated at 10MB, 7 generations kept (`sync.log.1` through `sync.log.7`). Inline rotation.

Per-device, not synced. Audit trail of what this device has done.

---

## Error hierarchy

```python
class MouiSyncError(Exception): ...

# Configuration
class ConfigValidationError(MouiSyncError): ...
class UnsupportedVersionError(MouiSyncError): ...
class RemoteNotFoundError(MouiSyncError): ...
class UnknownAdapterError(MouiSyncError): ...
class TargetMissingError(MouiSyncError): ...
class InfrastructureNotFoundError(MouiSyncError): ...

# Daemon lifecycle
class WorkspaceLockedError(MouiSyncError): ...
class FolderNotTrackedError(MouiSyncError): ...

# Transport / git
class SSHAccessError(MouiSyncError): ...
class GitCommandError(MouiSyncError): ...
class PushFailedError(MouiSyncError): ...
class PullFailedError(MouiSyncError): ...
class RepoDivergedError(MouiSyncError): ...

# Encryption
class EncryptionError(MouiSyncError): ...
class DecryptionError(MouiSyncError): ...
class InvalidRecipientError(MouiSyncError): ...
class SSHAgentUnavailableError(MouiSyncError): ...

# RPC
class UnknownMethodError(MouiSyncError): ...
class ProtocolVersionMismatchError(MouiSyncError): ...
```

---

## Module layout

After 017 merges into 018:

```
cli/
   commands/
      sync.py                       # mo sync entry, dispatches subcommands
   sync/
      __init__.py
      errors.py
      ulid_id.py
      config.py                     # pydantic models for sync declarations + device state
      git_sync.py                   # subprocess git wrapper
      client.py                     # JSON-RPC client; the cross-shape integration surface
      discovery.py                  # scan infrastructure/syncs/, build folder list
      transport/
         __init__.py
         base.py                    # Transport ABC, result types
         build.py                   # build_transport(folder_cfg, remote_cfg)
         encryption_wrapper.py
      encryption/
         __init__.py
         base.py                    # EncryptionLayer ABC
         none_layer.py
         age_ssh_layer.py
      daemon/
         __init__.py
         lock.py                    # pidfile + flock
         watcher.py                 # watchdog wrapper, per-folder debounce
         scheduler.py               # per-folder commit+push trigger
         events.py
         log_writer.py
         rpc.py
         server.py
         main.py                    # entry point: moui-sync daemon
      cli/
         __init__.py
         init_cmd.py
         sync_cmd.py
         status_cmd.py
         pull_cmd.py
         logs_cmd.py
         recipients_cmd.py
         forget_cmd.py
         rescan_cmd.py
         daemon_cmd.py

shapes/shared/adapters/
   git_sync.py                      # GitSyncAdapter — uses cli.sync.git_sync

tests/
   sync/
      conftest.py
      test_config.py
      test_discovery.py
      test_git_sync.py
      test_age_ssh_layer.py
      test_encryption_wrapper.py
      test_watcher_debounce.py
      test_rpc.py
      test_init_e2e.py
      test_second_device_e2e.py
```

**Architectural boundary:** `cli/sync/` is a black box from elsewhere in 018. The only legal import from non-sync code is `from cli.sync.client import SyncClient` (or similarly narrow exports). Sync code does not import shape-specific code. This enforces extractability.

`shapes/shared/adapters/git_sync.py` is the one boundary-crossing module: lives in `shapes/shared/` because that's where adapters live in 018, but imports `cli/sync/git_sync.py` for mechanical git work.

---

## Dependencies

```toml
[project]
dependencies = [
    "watchdog>=4.0",
    "pydantic>=2.0",
    "ruamel.yaml>=0.18",
    "python-ulid>=2.0",
    "pyrage>=1.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Stdlib for the rest: `asyncio`, `subprocess`, `logging`, `json`, `socket`, `pathlib`.

No `keyring`. No secrets-on-disk infrastructure. SSH agent is the sole key surface.

---

## Build sequence

Each step independently testable.

1. **`errors.py`, `ulid_id.py`** — primitives.
2. **`config.py`** — pydantic models for sync declarations and device state, strict validation, version checking, SSH-pubkey format validation.
3. **`discovery.py`** — scan `infrastructure/syncs/`, build folder list. Tested against fixture trees.
4. **`git_sync.py`** — subprocess wrapper for git operations: init, add remote, commit, push, pull, status. Environment scrubbing. Tested against local bare repo.
5. **`encryption/age_ssh_layer.py`** — `pyrage` with SSH-agent identities. Round-trip tests with a test SSH key.
6. **`transport/base.py`, `transport/encryption_wrapper.py`** — ABC and composition.
7. **`shapes/shared/adapters/git_sync.py`** — adapter using `cli/sync/git_sync.py`.
8. **`transport/build.py`** — single composition point.
9. **`daemon/lock.py`, `daemon/log_writer.py`, `daemon/events.py`** — small, testable.
10. **`daemon/rpc.py`, `daemon/server.py`** — JSON-RPC over Unix socket.
11. **`daemon/watcher.py`, `daemon/scheduler.py`** — per-folder debounced sync.
12. **`daemon/main.py`** — wires everything, takes `--infrastructure`.
13. **`client.py`** — JSON-RPC client for cross-shape integration.
14. **CLI subcommands** (`cli/sync/cli/`) and integration in `cli/commands/sync.py`.
15. **systemd unit + launchd plist + install script.**
16. **Sheets serve integration** — first demonstration of the shape-agnostic pattern.

---

## v3 deliberately omits

- Op-log-aware merging. Conflicts surface as `Diverged`; Reconciler layer is v1.
- LAN sync, relay, Yjs, mobile.
- Multiple infrastructure folders managed by one daemon.
- Auto-create remote via API.
- Folder rename detection.
- Conflict resolution UI.
- History rekeying when a recipient is removed.
- Passphrase-based encryption.
- Non-Ed25519 SSH key support.
- History squashing strategies.
- Cross-boundary file moves (moving files between folders with different remotes).

---

## Behaviors to confirm

- **First-init with non-empty folder and non-empty remote:** refuse. Require `--force-clone` (overwrite local with remote) or `--force-push` (overwrite remote with local). No silent merge.
- **Daemon crash mid-push:** on next startup, `git status` reflects current state per folder. Sync resumes.
- **Infrastructure path:** daemon receives `--infrastructure <path>` explicitly. Reads `<path>/remotes.yaml` and `<path>/syncs/`. No CWD inference.
- **Git author identity:** read from the remote config's `git_user`/`git_email`. The runtime sets `user.name`/`user.email` per-repo at init time.
- **Empty remote on first pull:** success with empty result.
- **SSH agent without matching key for encrypted folder:** at daemon startup, every encrypted folder's recipients are checked against the agent's public keys. Folders without a usable identity are flagged as `EncryptionUnavailable` and skipped; other folders continue.
- **Adding a recipient to an encrypted folder:** updates the declaration in `infrastructure/syncs/`, commits, pushes. Existing `.age` files are not re-encrypted.
- **Declaration for a target outside the infrastructure-parent tree:** `mo sync init` refuses. Hand-edited declarations with arbitrary `target` paths work at runtime, but the init flow only generates path-mirroring declarations.
- **Two daemons on the same infrastructure path:** the second fails with `WorkspaceLockedError`. The lock file path is derived from a hash of the infrastructure path, so different infrastructure folders get different locks.
- **`infrastructure/syncs/` missing or empty:** daemon starts, watches nothing, status shows "no declarations found, point `mo sync init` at a folder to start."
