# Moui Sync — v0.2 Spec

Per-folder git sync. SSH-agent auth and identity. Optional age-over-SSH encryption per folder. Integrates with 016's existing `infrastructure/remotes.yaml` and adapter conventions.

---

## Principles

Non-negotiable. Every implementation decision honors them.

- **Adapter-based.** Transport and encryption are interfaces with multiple implementations. Selection is by config, never by sniffing.
- **Declarative, nothing inferred.** Every behavior comes from explicit config. Missing config is an error. Defaults exist only for fields with universal values (debounce, ignore globs).
- **Throw always, make it loud.** No silent fallbacks. No exception swallowing. Every failure surfaces with a typed error and propagates.
- **No tight coupling.** Watcher does not know about transports. Transports do not know about the watcher. CLI talks to the daemon over a documented socket protocol, never by importing internals. Sync code shares no modules with deploy code.
- **No plaintext secrets.** SSH agent is the only key surface. The runtime stores no keys, generates no keys, manages no key material on disk.
- **Nothing hardcoded.** Workspace path, folder names, remotes — all declared by the user. No assumed conventions in code.

---

## Model

A workspace is a folder containing one or more tracked subfolders. Each tracked subfolder is its own git repo, synced to its own remote, with its own encryption setting. The daemon watches all declared folders, debounces changes, and runs commit + push per folder independently.

```
~/code/moui/                              ← workspace root, user-defined path
   .moui/
      workspace.yaml                      ← declares folders, remotes, encryption
      sync.log
      pid
   content/                               ← tracked folder, its own git repo
      .git/
      .gitignore
      ...
   infrastructure/                        ← tracked folder, its own git repo
      .git/
      .gitignore
      ...
   src/                                   ← not tracked; not in workspace.yaml
   pyproject.toml                         ← not tracked
```

The workspace root itself is **not** a git repo. Subfolders are independent repos. Files in the workspace root that aren't in declared folders are not seen by the sync runtime.

---

## Configuration: `.moui/workspace.yaml`

```yaml
version: 1

workspace:
  id: 01HK8QZ2N3X4Y5T6V7W8R9P0M1            # ULID, init-time
  device_id: 01HK8QZ2N3X4Y5T6V7W8R9P0M2     # ULID, per device
  display_name: "alex's laptop"
  root: .                                   # relative to workspace.yaml location

folders:
  content:
    remote: codeberg/moui-content-sync      # ID into infrastructure/remotes.yaml
    encryption:
      type: none

  infrastructure:
    remote: github/moui-infra-sync
    encryption:
      type: age-ssh
      recipients:
        - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... laptop"
        - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... work-machine"

sync:
  debounce_seconds: 10
  max_debounce_seconds: 60
  commit_message: "auto-sync: {timestamp}"
```

**Required fields:**

- `version`, `workspace.id`, `workspace.device_id`, `workspace.root`
- For each entry in `folders`: `remote`, `encryption.type`
- `encryption.type: age-ssh` requires non-empty `recipients`

**Validation:**

- Missing required field → `ConfigValidationError`
- Unknown top-level field → `ConfigValidationError` (`pydantic` strict + `extra="forbid"`)
- `remote` references an ID that doesn't exist in `infrastructure/remotes.yaml` → `RemoteNotFoundError` at daemon startup
- `recipients` entries that aren't valid SSH public keys → `InvalidRecipientError`
- `version` mismatch → `UnsupportedVersionError`

**No defaults for `remote`.** Every tracked folder declares its remote explicitly. Adding `defaults:` to fall back on is inference; we don't do it.

---

## Remote declarations

Sync remotes go in the existing `infrastructure/remotes.yaml`, alongside deploy remotes. New `adapter:` values: `codeberg_sync`, `github_sync`.

```yaml
# infrastructure/remotes.yaml
remotes:
  # existing deploy remotes
  codeberg/moui-pages:
    adapter: codeberg_pages
    repo: git@codeberg.org:moui/pages.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent

  # new sync remotes
  codeberg/moui-content-sync:
    adapter: codeberg_sync
    repo: git@codeberg.org:example/moui-content.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent

  github/moui-infra-sync:
    adapter: github_sync
    repo: git@github.com:example/moui-infra.git
    branch: main
    git_user: Alex Example
    git_email: alex@example.com
    credential: ssh-agent
```

Resolution: `cli/infra/remotes.py` (the existing loader) is called with the remote ID and returns the resolved entry. The daemon does not invent a parallel resolution path.

---

## Components

```
   CLI (mo sync …, mo sheets serve, etc.)
            │
            │ JSON-RPC over Unix socket
            ▼
   moui-sync daemon
      ├─ Lock                    (.moui/pid + flock)
      ├─ Watcher pool            (one per tracked folder)
      ├─ Scheduler               (per-folder debounced sync)
      ├─ EventBroadcaster
      ├─ LogWriter               (.moui/sync.log JSONL + rotation)
      └─ Per-folder Transport stack
            ├─ adapter: GithubSyncAdapter | CodebergSyncAdapter
            ├─ inner: GitSync (subprocess)
            └─ wrapper: EncryptionLayer (none | age-ssh)
```

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
    conflicts: list[Path]

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

`initialize` is the one-time setup: `git init` if needed, configure user.name/email, add remote, set tracking branch. Idempotent.

Result types are `pydantic` models, not bare dicts.

---

## Composition

The daemon builds a `Transport` per tracked folder, in one place:

```python
def build_transport(folder_cfg: FolderConfig, remote_cfg: dict) -> Transport:
    base: Transport = {
        "github_sync":   GithubSyncAdapter,
        "codeberg_sync": CodebergSyncAdapter,
    }[remote_cfg["adapter"]](remote_cfg)

    match folder_cfg.encryption.type:
        case "none":
            return base
        case "age-ssh":
            recipients = [pyrage.ssh.Recipient.from_str(r) for r in folder_cfg.encryption.recipients]
            return EncryptionWrapper(inner=base, recipients=recipients)
```

No registry, no plugin discovery, no string-keyed factory. Adding a transport or encryption type means editing this function. Composition is visible in one place.

---

## Encryption: age over SSH

When `encryption.type: age-ssh`:

**On commit:** for every plaintext file in the working tree (excluding gitignored paths and `.age` files), the runtime ensures `{path}.age` exists with current ciphertext, encrypted to the declared SSH recipients via `pyrage`. The `.age` files are tracked by git; plaintext is gitignored.

**On pull:** for every `.age` file that arrived or changed, decrypt to its plaintext path. Decryption requests the SSH agent for an Ed25519 key matching one of the encryption recipients. Deleted `.age` files trigger deletion of plaintext counterparts.

**Identity source:** SSH agent (`SSH_AUTH_SOCK`). The runtime stores no private keys, generates no keys, and manages no key material. `pyrage.ssh.Identity` reads from the agent at decrypt time.

**Invariant:** for every plaintext file P in the workspace (not otherwise gitignored), `P.age` exists and matches the current contents.

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
    plaintext_path = ciphertext_path.with_suffix("")  # strip .age
    plaintext_path.write_bytes(plaintext)
```

**Failure modes, all loud:**

- Decryption fails (no matching agent key) → `DecryptionError(file=..., cause="no matching SSH key in agent")`. Pull aborts. Working tree left in prior state.
- Encryption fails → `EncryptionError(file=..., cause=...)`. Commit aborts.
- Recipient malformed → `InvalidRecipientError(value=...)` at config load.
- SSH agent unavailable → `SSHAgentUnavailableError` at daemon startup for any folder using `age-ssh`.

**What leaks to the remote:** filenames, directory structure, file sizes, modification times. File contents are protected.

**No history rekeying.** Removing a recipient stops them from decrypting future commits but does not re-encrypt history. This is correct: removing a recipient cannot revoke access to commits they could already read. Documented limitation.

---

## Authentication

All git operations rely on SSH agent. The runtime invokes git with:

```
GIT_TERMINAL_PROMPT=0
SSH_AUTH_SOCK=<inherited>
```

If git prompts for credentials, it fails immediately rather than blocking. No password handling, no token storage, no HTTPS auth.

`mo sync init` verifies SSH access to each declared remote before writing config:

```
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@codeberg.org
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@github.com
```

Non-zero exit (other than the host's standard "auth ok, no shell" message) → `SSHAccessError(host=..., stderr=...)`.

---

## Watcher

One `watchdog` watcher per tracked folder. On any filesystem event in that folder (excluding ignored paths), the per-folder scheduler is poked. Each folder has its own debounce timer.

**Debounce:** events reset a per-folder timer set to fire `debounce_seconds` (default 10) ahead. Timer fire triggers sync.

**Maximum quiet window:** if events have continuously reset the timer for `max_debounce_seconds` (default 60), force a sync regardless. Prevents indefinite debounce under steady write pressure.

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

When `encryption.type: age-ssh`, an additional rule is appended that gitignores plaintext file extensions found in the folder. The rule is conservative — gitignore the specific extensions present at init time (`*.yaml`, `*.jsonl`, `*.md`, etc.) and require the user to add new types as they introduce them. No globbing all-files-except-`.age`; that's brittle.

---

## Pull policy

- **On daemon startup:** pull each tracked folder once. Surface results via the events stream.
- **On `mo sync pull [folder]`:** pull on demand, all folders or one.
- **Never auto-pull before push.** If push fails because remote is ahead, status reports `Diverged`. The user runs `mo sync pull <folder>` and resolves any conflicts.

This is the v0.2 limit. Op-log-aware merging is deferred to v1.

---

## CLI

```
mo sync init                                     interactive setup; writes workspace.yaml
mo sync init --join <remote_id> --as <folder>    clone a remote into a new tracked folder
mo sync status                                   per-folder state
mo sync status --watch                           live updates (TUI)
mo sync push [folder]                            force commit+push now (one folder, or all)
mo sync pull [folder]                            force pull now
mo sync logs                                     print recent .moui/sync.log entries
mo sync logs --follow                            follow mode
mo sync rescan                                   re-read workspace.yaml; pick up newly declared folders
mo sync recipients <folder> list                 show recipients for an encrypted folder
mo sync recipients <folder> add <ssh-pubkey>     add recipient, commit, push
mo sync recipients <folder> remove <ssh-pubkey>  remove recipient, commit, push (no history rekey)
mo sync daemon start|stop|restart|status         manage daemon process
```

`mo sync init` flow:

1. Discover existing top-level folders in workspace root, ask user which to track.
2. For each folder: prompt for remote ID (autocompletes from `infrastructure/remotes.yaml`), prompt for encryption type.
3. For each `age-ssh` folder: prompt for recipient SSH public keys. Accept paste or path to a `.pub` file. Validate format.
4. Verify SSH access to each declared remote.
5. Write `.moui/workspace.yaml` and `.moui/.gitignore` (which ignores `.moui/sync.log`, `.moui/pid`).
6. For each folder: `git init` if needed, configure user.name/user.email from remote config, add remote, write `<folder>/.gitignore` if missing.
7. Attempt initial pull per folder. Empty-remote case treated as success.
8. Start daemon.

`mo sync init --join` flow:

1. Resolve `<remote_id>` from `infrastructure/remotes.yaml`.
2. Clone the remote into `<workspace_root>/<folder>`.
3. If existing `workspace.yaml` exists, add a `folders:` entry; otherwise create `workspace.yaml` with the new folder declared.
4. If the cloned tree contains `.age` files, prompt user for the recipient list to record (the `.age` files don't tell us who else can decrypt — that's a workspace-config decision the user has to confirm).
5. Verify SSH agent has a key matching one of the recipients (otherwise pull will fail loudly later — better to surface here).
6. Done. User runs `mo sync daemon start` if not running.

Status output:

```
WORKSPACE  ~/code/moui   daemon: running (12s)

content              ●  clean        codeberg/moui-content-sync   (plain)         up to date
infrastructure       ●  dirty        github/moui-infra-sync       (age-ssh)       3 files, commit in 6s
                                                                                  (encrypted to 2 keys)
notes                ⚠  diverged     codeberg/moui-notes-sync     (plain)         5 ahead, 2 behind
```

---

## Daemon ↔ client protocol

JSON-RPC 2.0 over Unix socket.

- Linux: `$XDG_RUNTIME_DIR/moui-sync.sock`
- macOS: `~/Library/Application Support/moui/sync.sock`

Socket file permissions: `0o600`. Owner-only.

**Methods:**

```
status                                           → StatusResponse
push           { folder?: str }                  → list[SyncOutcome]
pull           { folder?: str }                  → list[PullOutcome]
rescan                                           → { added: list[str], removed: list[str] }
recipients.list    { folder: str }               → list[str]
recipients.add     { folder: str, pubkey: str }  → { recipients: list[str] }
recipients.remove  { folder: str, pubkey: str }  → { recipients: list[str] }
subscribe          { stream: "events" }          → streaming response
ping                                             → { ok: true, version, uptime_seconds }
```

Every request and response carries `version: 1`. Unknown method or version mismatch → typed JSON-RPC error envelope.

**Events stream:**

```json
{ "type": "sync.started",     "folder": "content", "ts": "..." }
{ "type": "sync.encrypted",   "folder": "infrastructure", "files": 3, "ts": "..." }
{ "type": "sync.committed",   "folder": "content", "sha": "abc123", "files": 3, "ts": "..." }
{ "type": "sync.pushed",      "folder": "content", "ts": "..." }
{ "type": "sync.error",       "folder": "content", "error_class": "PushFailedError", "detail": "...", "ts": "..." }
{ "type": "pull.started",     "folder": "content", "ts": "..." }
{ "type": "pull.decrypted",   "folder": "infrastructure", "files": 5, "ts": "..." }
{ "type": "pull.completed",   "folder": "content", "head": "def456", "ts": "..." }
{ "type": "watch.changed",    "folder": "content", "paths": ["..."], "ts": "..." }
```

Every event is folder-scoped. Subscribers can filter client-side.

---

## Renderer integration

`mo sheets serve <path>` resolves `<path>` to a tracked folder, connects to the daemon, subscribes to events filtered to that folder. The renderer's existing SSE channel forwards relevant events to the web UI.

UI status pill:

- `synced 3s ago`
- `syncing…`
- `↑ 2 ahead`
- `⚠ diverged — run 'mo sync pull content'`
- `⚠ decrypt error — see logs`
- `sync: offline` (daemon socket unavailable; renderer continues read-only)

If the served path is not in any tracked folder, the pill shows `not synced` and the renderer functions normally.

---

## Daemon lifecycle

**Linux** — systemd user service:

```ini
# ~/.config/systemd/user/moui-sync.service
[Unit]
Description=Moui Sync Daemon
After=network-online.target

[Service]
ExecStart=%h/.local/bin/moui-sync daemon --workspace %h/code/moui
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**macOS** — launchd agent at `~/Library/LaunchAgents/app.moui.sync.plist` with `RunAtLoad` and `KeepAlive`.

**Windows** — deferred.

**Foreground mode** for development: `moui-sync daemon --workspace ~/code/moui --foreground`.

**Single-instance per workspace:** `.moui/pid` locked with `flock`. A second daemon attempting to start on the same workspace exits with `WorkspaceLockedError(holder_pid=..., started_at=...)`. Different workspaces can have separate daemons concurrently.

---

## Sync log: `.moui/sync.log`

Append-only JSON Lines, same schema as the events stream. Rotated at 10MB, 7 generations kept (`sync.log.1` through `sync.log.7`). Rotation happens inline before each write that would exceed threshold.

---

## Error hierarchy

```python
class MouiSyncError(Exception): ...

# Configuration
class ConfigValidationError(MouiSyncError): ...
class UnsupportedVersionError(MouiSyncError): ...
class RemoteNotFoundError(MouiSyncError): ...

# Workspace lifecycle
class WorkspaceLockedError(MouiSyncError): ...
class WorkspaceNotInitializedError(MouiSyncError): ...
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

After 017 merges into 016:

```
cli/
   commands/
      sync.py                       # mo sync entry, dispatches subcommands
   sync/
      __init__.py
      errors.py                     # exception hierarchy
      ulid_id.py                    # ULID generation
      config.py                     # pydantic models for workspace.yaml
      git_sync.py                   # subprocess git wrapper, sync-specific primitives
      transport/
         __init__.py
         base.py                    # Transport ABC, result types
         build.py                   # build_transport(folder_cfg, remote_cfg)
         encryption_wrapper.py      # composes Transport + encryption
      encryption/
         __init__.py
         base.py                    # EncryptionLayer ABC
         none_layer.py              # passthrough
         age_ssh_layer.py           # pyrage with SSH-agent identities
      daemon/
         __init__.py
         lock.py                    # pidfile + flock
         watcher.py                 # watchdog wrapper, debounce
         scheduler.py               # per-folder commit+push trigger
         events.py                  # event types, broadcaster
         log_writer.py              # JSONL append + rotation
         rpc.py                     # JSON-RPC dispatch
         server.py                  # asyncio Unix socket server
         main.py                    # entry point: moui-sync daemon
      cli/
         __init__.py
         client.py                  # JSON-RPC client used by all subcommands
         init_cmd.py
         status_cmd.py
         push_cmd.py
         pull_cmd.py
         logs_cmd.py
         recipients_cmd.py
         rescan_cmd.py
         daemon_cmd.py

shapes/shared/adapters/
   codeberg_sync.py                 # CodebergSyncAdapter — uses cli.sync.git_sync
   github_sync.py                   # GithubSyncAdapter — uses cli.sync.git_sync

tests/
   sync/
      conftest.py
      test_config.py
      test_git_sync.py
      test_age_ssh_layer.py
      test_encryption_wrapper.py
      test_watcher_debounce.py
      test_rpc.py
      test_init_e2e.py
```

`shapes/shared/adapters/codeberg_sync.py` and `github_sync.py` are thin — URL templating and adapter-name registration. They do not share modules with `codeberg_pages.py` or `git_pages.py`. The mechanical git work for sync lives in `cli/sync/git_sync.py`.

CLI entry in `cli/commands/sync.py` follows the convention used by `cli/commands/deploy.py` and `cli/commands/serve.py`.

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
2. **`config.py`** — pydantic models, strict validation, version checking, recipient SSH-pubkey validation.
3. **`git_sync.py`** — subprocess wrapper for git operations: init, add remote, commit, push, pull, status. Environment scrubbing (`GIT_TERMINAL_PROMPT=0`). Tested against a local bare repo.
4. **`encryption/age_ssh_layer.py`** — `pyrage` with SSH-agent identities. Round-trip tests using a test SSH key in a test agent.
5. **`transport/base.py`, `transport/encryption_wrapper.py`** — ABC and composition.
6. **`shapes/shared/adapters/codeberg_sync.py`, `github_sync.py`** — adapter implementations using `git_sync.py`.
7. **`transport/build.py`** — single composition point.
8. **`daemon/lock.py`, `daemon/log_writer.py`, `daemon/events.py`** — small, testable.
9. **`daemon/rpc.py`, `daemon/server.py`** — JSON-RPC over Unix socket.
10. **`daemon/watcher.py`, `daemon/scheduler.py`** — per-folder debounced sync.
11. **`daemon/main.py`** — wires everything, takes `--workspace`.
12. **CLI subcommands** (`cli/sync/cli/`) and integration in `cli/commands/sync.py`.
13. **systemd unit + launchd plist + install script.**
14. **Sheets serve integration** — subscribe to events filtered by folder, expose via SSE.

---

## v0.2 deliberately omits

- Op-log-aware merging. Conflicts surface as `Diverged`; user resolves manually.
- LAN sync, relay, Yjs, mobile.
- Multiple workspaces simultaneously on one device (single-instance is per-workspace, but the CLI assumes one workspace at a time).
- Auto-create remote via API. Remotes are created out-of-band on the forge UI.
- Folder rename detection.
- Conflict resolution UI.
- History rekeying when a recipient is removed.
- Passphrase-based encryption.
- Non-Ed25519 SSH key support for age-ssh. Only Ed25519 in v0.2.

---

## Behaviors to confirm

- **First-init with non-empty folder and non-empty remote:** refuse. Require `--force-clone` (overwrite local with remote) or `--force-push` (overwrite remote with local). No silent merge.
- **Daemon crash mid-push:** on next startup, `git status` reflects current state per folder. Sync resumes from there.
- **Workspace path:** daemon receives `--workspace <path>` explicitly. Reads `<path>/.moui/workspace.yaml`. No CWD inference, no env-var fallback.
- **Git author identity:** read from the remote config's `git_user` and `git_email` fields. The runtime sets `user.name` and `user.email` per-repo at init time. Never auto-pulls from `git config --global` because that's inference about the user's intent.
- **Empty remote on first pull:** treated as success with empty result, not as an error.
- **SSH agent without a matching key for an encrypted folder:** at daemon startup, every encrypted folder's recipients are checked against the agent's public keys. If no folder has a usable identity, daemon refuses to start. If some folders have usable identities and others don't, the unusable ones are flagged as `EncryptionUnavailable` and skipped; the daemon runs and serves the rest.
- **Adding a recipient to an encrypted folder:** updates `workspace.yaml`, commits, pushes. Existing `.age` files are not re-encrypted; only commits made after the recipient was added include them. Documented behavior, not a bug.
