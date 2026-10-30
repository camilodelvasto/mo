# Moui Sync — v0.3 Spec

Per-folder git sync. SSH-agent auth and identity. Optional age-over-SSH encryption per folder. Integrates with 016's existing `infrastructure/remotes.yaml` conventions.

---

## Principles

Non-negotiable. Every implementation decision honors them.

- **Adapter-based.** Transport and encryption are interfaces. Selection is by config, never by sniffing.
- **Declarative, nothing inferred.** Every behavior comes from explicit config. Missing config is an error. Defaults exist only for fields with universal values.
- **Throw always, make it loud.** No silent fallbacks. No exception swallowing. Every failure surfaces with a typed error and propagates.
- **No tight coupling.** Watcher does not know about transports. Transports do not know about the watcher. CLI talks to the daemon over a documented socket protocol. Sync code shares no modules with deploy code.
- **No plaintext secrets.** SSH agent is the only key surface. The runtime stores no keys, generates no keys, manages no key material on disk.
- **Nothing hardcoded.** Workspace path, folder names, remotes — all declared by the user.

---

## Git as infrastructure, not as protocol

Git is not an ideal sync protocol. Commit-per-sync produces noisy history. Text-merge does not understand op-log shapes. Two writers editing the same row produce a conflict git cannot resolve semantically. These are real limits, acknowledged.

Git is chosen because it is excellent *infrastructure*. The transport is SSH to a forge. Git provides the consistency model — a content-addressed log any peer can fetch and reconcile. From this we get five things a custom protocol does not give us:

- Authentication via existing SSH agent. No new identity infrastructure.
- Durable storage on infrastructure we don't run. No relays, no buckets, no operational burden.
- A working browse/review UI on every forge. Synced data is inspectable in a web browser without any Moui tooling.
- Conflict detection for free (push refusal when remote is ahead).
- A scriptable escape hatch. When sync goes wrong, the user has a standard tool to fix it.

The trade-off: history is noisy and conflicts on shape-aware files (op-logs) are not auto-merged in v0.3. Both are addressable later without changing the Transport interface. Squashing strategies and shape-aware reconciliation slot in as layers above the transport, not as transport changes.

---

## Conflict reporting vs. conflict resolution

The Transport detects divergence and reports it via `PullOutcome.conflicts`. It does not resolve.

In v0.3, the daemon receives the conflict list and surfaces it via status; the user resolves manually with git. In v1, a separate `Reconciler` layer will subscribe to conflict events, examine the conflicting paths, and dispatch to shape-aware merge logic (op-log merge for `ops.jsonl`, Yjs merge for CRDT-backed shapes, etc.). The Transport interface does not change. **`PullOutcome.conflicts` is the seam where v1's Reconciler plugs in.**

---

## Model

A workspace is a folder containing one or more tracked subfolders. Each tracked subfolder is its own git repo, synced to its own remote, with its own encryption setting and its own debounce timing. The daemon watches all declared folders and runs sync per folder independently.

```
~/code/moui/                              ← workspace root, user-defined path
   .moui/
      device.yaml                         ← per-device, never tracked
      sync.log
      pid
   content/                               ← tracked folder, its own git repo
      .git/
      .moui/
         workspace.yaml                   ← workspace declaration (tracked)
      .gitignore
      ...
   infrastructure/                        ← tracked folder, its own git repo
      .git/
      .gitignore
      ...
```

The workspace root is **not** a git repo. Tracked subfolders are independent repos. Files outside tracked folders are invisible to the sync runtime.

The first folder declared in `workspace.yaml` is the **bootstrap folder**. By convention, this folder contains the workspace declaration at `<bootstrap_folder>/.moui/workspace.yaml`. New devices clone the bootstrap folder first, read its workspace.yaml, and learn about the other folders to clone.

---

## Configuration

### `<bootstrap_folder>/.moui/workspace.yaml` (tracked)

```yaml
version: 1

workspace:
  id: 01HK8QZ2N3X4Y5T6V7W8R9P0M1
  display_name: "moui main workspace"

folders:
  # first entry is the bootstrap folder by convention
  content:
    remote: codeberg/moui-content-sync
    encryption:
      type: none
    sync:                                  # optional per-folder override
      debounce_seconds: 30                 # longer for writing sessions
      max_debounce_seconds: 300

  infrastructure:
    remote: github/moui-infra-sync
    encryption:
      type: age-ssh
      recipients:
        - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... laptop"
        - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... work-machine"

sync:                                      # workspace-level defaults
  debounce_seconds: 10
  max_debounce_seconds: 60
  commit_message: "auto-sync: {timestamp}"
```

### `.moui/device.yaml` (per-device, untracked)

```yaml
version: 1

device:
  id: 01HK8QZ2N3X4Y5T6V7W8R9P0M2
  display_name: "alex's laptop"
  workspace_id: 01HK8QZ2N3X4Y5T6V7W8R9P0M1  # must match workspace.yaml
  workspace_root: ~/code/moui                # absolute or ~/-relative
  bootstrap_folder: content                  # which folder holds workspace.yaml
```

### Validation

- Missing required field in either file → `ConfigValidationError`
- Unknown top-level field → `ConfigValidationError` (`pydantic` strict + `extra="forbid"`)
- `device.workspace_id` does not match `workspace.id` → `WorkspaceMismatchError`
- `remote` references an ID absent from `infrastructure/remotes.yaml` → `RemoteNotFoundError`
- `recipients` entries that aren't valid SSH public keys → `InvalidRecipientError`
- `version` mismatch in either file → `UnsupportedVersionError`

### What's required vs optional

- Per-folder `remote` and `encryption.type` are required. No defaults.
- Per-folder `sync:` block is optional; missing fields inherit from workspace-level `sync:`.
- Workspace-level `sync.debounce_seconds` and `sync.max_debounce_seconds` have built-in defaults (10s and 60s) because they have universal sensible values.

---

## Remote declarations

Sync remotes go in the existing `infrastructure/remotes.yaml` alongside deploy remotes. The new adapter value: `git_sync`.

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

  # new sync remotes — same adapter for any git-over-SSH forge
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

The SSH host comes from the `repo` URL. The adapter is forge-agnostic; Codeberg and GitHub are not distinguished because git-over-SSH behaves identically for both. If forge-specific behavior is ever needed (e.g. auto-create-repo via API), it's added as a separate adapter or a capability flag, not pre-emptively split.

Remote resolution uses the existing `cli/infra/remotes.py` loader. The sync code does not invent a parallel resolution path.

---

## Components

```
   CLI (mo sync …, mo sheets serve, mo grove serve, etc.)
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
            ├─ adapter: GitSyncAdapter
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

The daemon builds a `Transport` per tracked folder in one place:

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
    plaintext_path = ciphertext_path.with_suffix("")
    plaintext_path.write_bytes(plaintext)
```

**Failure modes, all loud:**

- Decryption fails → `DecryptionError(file=..., cause="no matching SSH key in agent")`. Pull aborts; working tree left in prior state.
- Encryption fails → `EncryptionError(file=..., cause=...)`. Commit aborts.
- Recipient malformed → `InvalidRecipientError(value=...)` at config load.
- SSH agent unavailable → `SSHAgentUnavailableError` at daemon startup for any folder using `age-ssh`.

**What leaks to the remote:** filenames, directory structure, file sizes, modification times. File contents are protected.

**No history rekeying.** Removing a recipient stops future commits from being encrypted to them but does not re-encrypt existing history. Documented limitation, not a bug.

**Ed25519 only in v0.3.** RSA SSH keys for age are not enabled. Modern tooling defaults to Ed25519.

---

## Authentication

All git operations rely on SSH agent. The runtime invokes git with:

```
GIT_TERMINAL_PROMPT=0
SSH_AUTH_SOCK=<inherited>
```

If git prompts for credentials, it fails immediately. No password handling, no token storage, no HTTPS auth.

`mo sync init` verifies SSH access to each declared remote before writing config:

```
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@<host>
```

Non-zero exit (other than the host's standard "auth ok, no shell" message) → `SSHAccessError`.

---

## Watcher

One `watchdog` watcher per tracked folder. On any filesystem event in that folder (excluding ignored paths), the per-folder scheduler is poked. Each folder has its own debounce timer.

**Debounce:** events reset a per-folder timer set to fire `debounce_seconds` ahead. Folder-level value overrides workspace-level default.

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

For the bootstrap folder, `.moui/sync.log` and `.moui/pid` are also added (but `.moui/workspace.yaml` is **not** ignored — it's the tracked workspace declaration). `.moui/device.yaml` lives at the workspace root, outside any tracked folder, so it's invisible to per-folder gitignores.

When `encryption.type: age-ssh`, an additional rule gitignores plaintext file extensions found in the folder. Conservative: gitignore the specific extensions present at init time (`*.yaml`, `*.jsonl`, `*.md`, etc.) and require the user to add new types explicitly. No globbing all-files-except-`.age`.

---

## Pull policy

- **On daemon startup:** pull each tracked folder once. Surface results via events.
- **On `mo sync pull [folder]`:** pull on demand.
- **Never auto-pull before push.** Push failures due to remote-ahead surface as `Diverged`; the user runs `mo sync pull <folder>`.

Op-log-aware merging is deferred to v1 via the Reconciler layer.

---

## CLI

```
mo sync init                                     interactive setup; first device
mo sync init --join <remote_id>                  clone bootstrap folder, read workspace.yaml, then iterative folder clones
mo sync status                                   per-folder state
mo sync status --watch                           live updates (TUI)
mo sync push [folder]                            force commit+push (all or one)
mo sync pull [folder]                            force pull (all or one)
mo sync logs                                     print recent .moui/sync.log entries
mo sync logs --follow                            follow mode
mo sync rescan                                   re-read workspace.yaml; pick up newly declared folders
mo sync recipients <folder> list                 show recipients
mo sync recipients <folder> add <ssh-pubkey>     add recipient, commit, push
mo sync recipients <folder> remove <ssh-pubkey>  remove recipient (no history rekey)
mo sync daemon start|stop|restart|status         manage daemon process
```

### `mo sync init` (first device)

1. Prompt for workspace display name and root path.
2. Discover existing top-level folders in workspace root; ask user which to track.
3. Ask which folder is the **bootstrap folder** (will hold `.moui/workspace.yaml`). Defaults to the first selected folder.
4. For each tracked folder:
   - Prompt for remote ID (autocompletes from `infrastructure/remotes.yaml`).
   - Prompt for encryption type.
   - For `age-ssh`: prompt for recipient SSH public keys (paste or `.pub` file path).
   - Optionally configure per-folder debounce overrides.
5. Verify SSH access to each declared remote.
6. Write `<bootstrap_folder>/.moui/workspace.yaml` and `.moui/device.yaml` at workspace root.
7. For each folder: `git init` if needed, configure user.name/user.email from remote config, add remote, write `<folder>/.gitignore`.
8. Initial pull per folder. Empty remote treated as success.
9. Start daemon.

### `mo sync init --join <remote_id>`

1. Resolve `<remote_id>` from `infrastructure/remotes.yaml`.
2. Prompt for workspace root path (where the workspace will live on this device).
3. Clone the resolved remote into `<workspace_root>/<derived_folder_name>`. The folder name is derived from the remote ID's last segment (`codeberg/moui-content-sync` → `moui-content-sync` → user-confirmed; default proposes a sensible name based on the cloned repo's contents).
4. Read `<cloned_folder>/.moui/workspace.yaml`. If missing, error: "this remote is not a workspace bootstrap folder."
5. Validate the cloned folder's name matches a `folders:` entry in `workspace.yaml`. If not, prompt user to rename or override.
6. Write `.moui/device.yaml` at workspace root with this device's ID and the discovered workspace ID.
7. Display the full folder list from `workspace.yaml` and prompt: "this workspace also tracks: `infrastructure`, `notes`. Clone now? [Y/n]"
8. For each additional folder the user accepts:
   - Resolve its remote ID from `infrastructure/remotes.yaml` (must already exist on this device).
   - Clone into `<workspace_root>/<folder_name>`.
   - For encrypted folders: verify SSH agent has a matching key; warn loudly if not.
9. Start daemon.

If `infrastructure/remotes.yaml` is missing some of the referenced remote IDs on the new device, the join flow prints which ones are missing and what to add. It does not invent or fetch them.

### Status output

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

Socket permissions: `0o600`. Owner-only.

**Methods:**

```
status                                           → StatusResponse
push           { folder?: str }                  → list[SyncOutcome]
pull           { folder?: str }                  → list[PullOutcome]
rescan                                           → { added: list[str], removed: list[str] }
recipients.list    { folder: str }               → list[str]
recipients.add     { folder: str, pubkey: str }  → { recipients: list[str] }
recipients.remove  { folder: str, pubkey: str }  → { recipients: list[str] }
subscribe          { stream: "events", folder?: str }  → streaming response
ping                                             → { ok: true, version, uptime_seconds }
```

Every request and response carries `version: 1`. Unknown method or version mismatch → typed JSON-RPC error envelope.

**Events stream** (all events are folder-scoped):

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

Subscribers may pass a `folder` filter to receive only events for a specific tracked folder.

---

## Renderer integration — shape-agnostic

Sync status integration is a **cross-shape pattern**. Any shape's `serve` command may subscribe to the daemon and surface sync state in its UI. The integration is not sheets-specific.

The integration surface is the JSON-RPC client at `cli/sync/client.py`. Each shape's serve imports it, subscribes to events filtered by its folder, and forwards them via its existing UI channel (SSE, WebSocket, polling — whatever that shape already uses).

For v0.3, sheets is the demonstration. Grove and deck integrate the same way when their renderers grow to need it. The contract is documented; the consumers grow independently.

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
ExecStart=%h/.local/bin/moui-sync daemon --workspace %h/code/moui
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**macOS** — launchd agent at `~/Library/LaunchAgents/app.moui.sync.plist` with `RunAtLoad` and `KeepAlive`.

**Windows** — deferred.

**Foreground mode** for development: `moui-sync daemon --workspace ~/code/moui --foreground`.

**Single-instance per workspace:** `.moui/pid` locked with `flock`. Second daemon on same workspace exits with `WorkspaceLockedError`. Different workspaces can have separate daemons concurrently.

---

## Sync log: `.moui/sync.log`

Append-only JSON Lines, same schema as events stream. Rotated at 10MB, 7 generations kept (`sync.log.1` through `sync.log.7`). Inline rotation; no background task.

---

## Error hierarchy

```python
class MouiSyncError(Exception): ...

# Configuration
class ConfigValidationError(MouiSyncError): ...
class UnsupportedVersionError(MouiSyncError): ...
class RemoteNotFoundError(MouiSyncError): ...
class WorkspaceMismatchError(MouiSyncError): ...
class UnknownAdapterError(MouiSyncError): ...

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
      errors.py
      ulid_id.py
      config.py                     # pydantic models for workspace.yaml + device.yaml
      git_sync.py                   # subprocess git wrapper, sync-specific primitives
      client.py                     # JSON-RPC client; the cross-shape integration surface
      transport/
         __init__.py
         base.py                    # Transport ABC, result types
         build.py                   # build_transport(folder_cfg, remote_cfg)
         encryption_wrapper.py      # composes Transport + encryption
      encryption/
         __init__.py
         base.py                    # EncryptionLayer ABC
         none_layer.py
         age_ssh_layer.py           # pyrage with SSH-agent identities
      daemon/
         __init__.py
         lock.py                    # pidfile + flock
         watcher.py                 # watchdog wrapper, per-folder debounce
         scheduler.py               # per-folder commit+push trigger
         events.py                  # event types, broadcaster
         log_writer.py              # JSONL append + rotation
         rpc.py                     # JSON-RPC dispatch
         server.py                  # asyncio Unix socket server
         main.py                    # entry point: moui-sync daemon
      cli/
         __init__.py
         init_cmd.py
         status_cmd.py
         push_cmd.py
         pull_cmd.py
         logs_cmd.py
         recipients_cmd.py
         rescan_cmd.py
         daemon_cmd.py

shapes/shared/adapters/
   git_sync.py                      # GitSyncAdapter — uses cli.sync.git_sync

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
      test_join_e2e.py
```

`shapes/shared/adapters/git_sync.py` is thin — adapter registration, instantiation. Mechanical git work lives in `cli/sync/git_sync.py`. No code shared with `codeberg_pages.py` or `git_pages.py`.

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
2. **`config.py`** — pydantic models for both `workspace.yaml` and `device.yaml`, strict validation, version checking, SSH-pubkey validation.
3. **`git_sync.py`** — subprocess wrapper: init, add remote, commit, push, pull, status. Environment scrubbing. Tested against local bare repo.
4. **`encryption/age_ssh_layer.py`** — `pyrage` with SSH-agent identities. Round-trip tests with a test SSH key.
5. **`transport/base.py`, `transport/encryption_wrapper.py`** — ABC and composition.
6. **`shapes/shared/adapters/git_sync.py`** — adapter using `cli/sync/git_sync.py`.
7. **`transport/build.py`** — single composition point.
8. **`daemon/lock.py`, `daemon/log_writer.py`, `daemon/events.py`** — small, testable.
9. **`daemon/rpc.py`, `daemon/server.py`** — JSON-RPC over Unix socket.
10. **`daemon/watcher.py`, `daemon/scheduler.py`** — per-folder debounced sync.
11. **`daemon/main.py`** — wires everything, takes `--workspace`.
12. **`client.py`** — JSON-RPC client for cross-shape integration.
13. **CLI subcommands** (`cli/sync/cli/`) and integration in `cli/commands/sync.py`.
14. **systemd unit + launchd plist + install script.**
15. **Sheets serve integration** — first demonstration of the shape-agnostic pattern.

---

## v0.3 deliberately omits

- Op-log-aware merging. Conflicts surface as `Diverged`; Reconciler layer is v1.
- LAN sync, relay, Yjs, mobile.
- Multiple workspaces simultaneously on one device.
- Auto-create remote via API. Remotes created out-of-band on the forge.
- Folder rename detection.
- Conflict resolution UI.
- History rekeying when a recipient is removed.
- Passphrase-based encryption.
- Non-Ed25519 SSH key support.
- History squashing strategies.

---

## Behaviors to confirm

- **First-init with non-empty folder and non-empty remote:** refuse. Require `--force-clone` or `--force-push`. No silent merge.
- **Daemon crash mid-push:** on next startup, `git status` reflects current state per folder. Sync resumes from there.
- **Workspace path:** daemon receives `--workspace <path>` explicitly. Reads `<path>/.moui/device.yaml`, then `<path>/<bootstrap_folder>/.moui/workspace.yaml`. No CWD inference.
- **Git author identity:** read from the remote config's `git_user` and `git_email`. The runtime sets `user.name` and `user.email` per-repo at init time.
- **Empty remote on first pull:** treated as success with empty result.
- **SSH agent without matching key for encrypted folder:** at daemon startup, every encrypted folder's recipients are checked against the agent's public keys. Folders without a usable identity are flagged as `EncryptionUnavailable` and skipped; other folders continue. Status surfaces the unusable state loudly.
- **Adding a recipient to an encrypted folder:** updates `workspace.yaml`, commits, pushes. Existing `.age` files are not re-encrypted; recipients gain access to commits made after their addition.
- **Bootstrap folder change:** if a user wants to change which folder holds `.moui/workspace.yaml`, they manually move the file, update `device.yaml`, and commit. v0.3 has no command for this.
