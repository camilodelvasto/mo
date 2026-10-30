"""Moui sync daemon entry point."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import signal
from pathlib import Path

from cli.infra.remotes import get_remote, load_remotes
from cli.sync.config import SyncSettings
from cli.sync.daemon.events import EventBroadcaster, SyncEvent
from cli.sync.daemon.lock import acquire_lock, release_lock
from cli.sync.daemon.log_writer import LogWriter
from cli.sync.daemon.rpc import RPCDispatcher
from cli.sync.daemon.scheduler import FolderScheduler
from cli.sync.daemon.server import RPCServer
from cli.sync.daemon.watcher import FolderWatcher
from cli.sync.discovery import discover_declarations
from cli.sync.errors import MouiSyncError, PushFailedError
from cli.sync.transport.base import Transport
from cli.sync.transport.build import build_transport

logger = logging.getLogger("moui.sync.daemon")


def _config_dir() -> Path:
    """Per-user config directory for sync state."""
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "moui" / "sync"
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "moui" / "sync"


class SyncDaemon:
    def __init__(self, infrastructure_path: Path) -> None:
        self._infrastructure_path = infrastructure_path.resolve()
        self._config_dir = _config_dir()
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._lock_fd: int | None = None
        self._remotes: dict = {}
        self._transports: dict[str, Transport] = {}
        self._sync_settings: dict[str, SyncSettings] = {}
        self._schedulers: dict[str, FolderScheduler] = {}
        self._watchers: dict[str, FolderWatcher] = {}
        self._pull_tasks: dict[str, asyncio.Task] = {}
        self._broadcaster = EventBroadcaster()
        self._log_writer: LogWriter | None = None
        self._rpc_server: RPCServer | None = None

    async def start(self) -> None:
        # 1. Acquire lock
        pid_path = self._config_dir / "pid"
        self._lock_fd = acquire_lock(pid_path)
        logger.info("lock acquired at %s", pid_path)

        # 2. Discover declarations
        resolved = discover_declarations(self._infrastructure_path)
        logger.info("discovered %d declarations", len(resolved))

        if not resolved:
            logger.info("no declarations found — watching nothing")

        # 3. Load remotes
        self._remotes = load_remotes(self._infrastructure_path.parent)

        # 4. Create LogWriter
        self._log_writer = LogWriter(self._config_dir / "sync.log")

        loop = asyncio.get_running_loop()

        # 5. For each declaration: build transport, initialize, create scheduler + watcher + pull loop
        for rf in resolved:
            folder_key = str(rf.folder_path)
            remote_cfg = get_remote(self._remotes, rf.declaration.remote)
            transport = build_transport(rf.declaration, remote_cfg)

            transport.initialize(rf.folder_path, remote_cfg)
            self._transports[folder_key] = transport

            decl_sync = rf.declaration.sync or SyncSettings()
            self._sync_settings[folder_key] = decl_sync

            scheduler = FolderScheduler(
                folder_name=folder_key,
                debounce_seconds=decl_sync.debounce_seconds,
                max_debounce_seconds=decl_sync.max_debounce_seconds,
                on_sync=self._do_sync,
                loop=loop,
            )
            self._schedulers[folder_key] = scheduler

            watcher = FolderWatcher(rf.folder_path, scheduler)
            watcher.start()
            self._watchers[folder_key] = watcher

        # 6. Build RPC dispatcher
        dispatcher = self._build_rpc_dispatcher()

        # 7. Start RPC server
        self._rpc_server = RPCServer(dispatcher)
        await self._rpc_server.start()
        logger.info("RPC server started")

        # 8. Initial pull per folder, then start periodic pull loops
        for folder_key in self._transports:
            try:
                await self._do_pull(folder_key)
            except Exception as exc:
                await self._emit(SyncEvent(
                    type="pull.error",
                    folder=folder_key,
                    error=str(exc),
                ))
                logger.warning("initial pull failed for %s: %s", folder_key, exc)

            # Start periodic pull
            interval = self._sync_settings[folder_key].pull_interval_seconds
            task = asyncio.create_task(self._pull_loop(folder_key, interval))
            self._pull_tasks[folder_key] = task

    async def stop(self) -> None:
        # Cancel pull loops
        for task in self._pull_tasks.values():
            task.cancel()
        self._pull_tasks.clear()

        for watcher in self._watchers.values():
            watcher.stop()
        self._watchers.clear()

        for scheduler in self._schedulers.values():
            scheduler.cancel()
        self._schedulers.clear()

        if self._rpc_server is not None:
            await self._rpc_server.stop()
            self._rpc_server = None

        if self._lock_fd is not None:
            release_lock(self._lock_fd, self._config_dir / "pid")
            self._lock_fd = None

        logger.info("daemon stopped")

    async def rescan(self) -> dict:
        """Re-discover declarations and update watchers."""
        new_resolved = discover_declarations(self._infrastructure_path)
        new_keys = {str(rf.folder_path) for rf in new_resolved}
        old_keys = set(self._transports.keys())

        added = new_keys - old_keys
        removed = old_keys - new_keys

        loop = asyncio.get_running_loop()

        # Remove old
        for key in removed:
            if key in self._pull_tasks:
                self._pull_tasks[key].cancel()
                del self._pull_tasks[key]
            if key in self._watchers:
                self._watchers[key].stop()
                del self._watchers[key]
            if key in self._schedulers:
                self._schedulers[key].cancel()
                del self._schedulers[key]
            if key in self._transports:
                del self._transports[key]
            if key in self._sync_settings:
                del self._sync_settings[key]

        # Add new
        for rf in new_resolved:
            key = str(rf.folder_path)
            if key in added:
                remote_cfg = get_remote(self._remotes, rf.declaration.remote)
                transport = build_transport(rf.declaration, remote_cfg)
                transport.initialize(rf.folder_path, remote_cfg)
                self._transports[key] = transport

                decl_sync = rf.declaration.sync or SyncSettings()
                self._sync_settings[key] = decl_sync

                scheduler = FolderScheduler(
                    folder_name=key,
                    debounce_seconds=decl_sync.debounce_seconds,
                    max_debounce_seconds=decl_sync.max_debounce_seconds,
                    on_sync=self._do_sync,
                    loop=loop,
                )
                self._schedulers[key] = scheduler

                watcher = FolderWatcher(rf.folder_path, scheduler)
                watcher.start()
                self._watchers[key] = watcher

                interval = decl_sync.pull_interval_seconds
                task = asyncio.create_task(self._pull_loop(key, interval))
                self._pull_tasks[key] = task

        return {"added": list(added), "removed": list(removed)}

    async def _pull_loop(self, folder_key: str, interval_seconds: int) -> None:
        """Periodically pull from remote."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self._do_pull(folder_key)
            except Exception as exc:
                await self._emit(SyncEvent(
                    type="pull.error",
                    folder=folder_key,
                    error=str(exc),
                ))
                logger.error("periodic pull failed for %s: %s", folder_key, exc)

    async def _do_sync(self, folder_key: str) -> None:
        """Commit + push. On push rejection (remote ahead), pull then retry once."""
        await self._emit(SyncEvent(type="sync.started", folder=folder_key))
        try:
            folder_path = Path(folder_key)
            transport = self._transports[folder_key]
            outcome = transport.sync(folder_path)
            if outcome.committed_sha:
                await self._emit(SyncEvent(
                    type="sync.committed",
                    folder=folder_key,
                    sha=outcome.committed_sha,
                ))
            if outcome.pushed:
                await self._emit(SyncEvent(
                    type="sync.pushed",
                    folder=folder_key,
                ))
        except PushFailedError:
            logger.info("push rejected for %s — pulling and retrying", folder_key)
            await self._emit(SyncEvent(
                type="sync.push_rejected",
                folder=folder_key,
                error="remote ahead — pulling and retrying",
            ))
            try:
                await self._do_pull(folder_key)
                # Retry push
                outcome = transport.sync(folder_path)
                if outcome.pushed:
                    await self._emit(SyncEvent(
                        type="sync.pushed",
                        folder=folder_key,
                    ))
            except Exception as exc:
                await self._emit(SyncEvent(
                    type="sync.error",
                    folder=folder_key,
                    error=f"retry after pull failed: {exc}",
                ))
                logger.error("sync retry failed for %s: %s", folder_key, exc)
        except Exception as exc:
            await self._emit(SyncEvent(
                type="sync.error",
                folder=folder_key,
                error=str(exc),
            ))
            logger.error("sync failed for %s: %s", folder_key, exc)

    async def _do_pull(self, folder_key: str) -> None:
        await self._emit(SyncEvent(type="pull.started", folder=folder_key))
        try:
            folder_path = Path(folder_key)
            transport = self._transports[folder_key]
            outcome = transport.pull(folder_path)
            if outcome.conflicts:
                await self._emit(SyncEvent(
                    type="pull.conflicts",
                    folder=folder_key,
                    error=f"merge conflicts: {', '.join(outcome.conflicts)}",
                ))
                logger.error(
                    "CONFLICTS in %s: %s — resolve manually with git",
                    folder_key, outcome.conflicts,
                )
            else:
                await self._emit(SyncEvent(
                    type="pull.completed",
                    folder=folder_key,
                    head=outcome.head,
                    merged=len(outcome.merged_commits),
                ))
        except Exception as exc:
            await self._emit(SyncEvent(
                type="pull.error",
                folder=folder_key,
                error=str(exc),
            ))
            logger.error("pull failed for %s: %s", folder_key, exc)

    async def _emit(self, event: SyncEvent) -> None:
        if self._log_writer is not None:
            self._log_writer.write(event)
        await self._broadcaster.emit(event)

    def _build_rpc_dispatcher(self) -> RPCDispatcher:
        dispatcher = RPCDispatcher()

        @dispatcher.method("ping")
        async def _ping(params: dict | None) -> dict:
            return {"ok": True, "version": 1}

        @dispatcher.method("status")
        async def _status(params: dict | None) -> dict:
            result = {}
            for folder_key, transport in self._transports.items():
                folder_path = Path(folder_key)
                try:
                    st = transport.status(folder_path)
                    result[folder_key] = st.model_dump()
                except Exception as exc:
                    result[folder_key] = {"state": "error", "error": str(exc)}
            return result

        @dispatcher.method("sync")
        async def _sync(params: dict | None) -> dict:
            folder = params["folder"]
            if folder not in self._transports:
                raise MouiSyncError(f"unknown folder: {folder}")
            await self._do_sync(folder)
            return {"ok": True}

        @dispatcher.method("push")
        async def _push(params: dict | None) -> list:
            targets = self._resolve_targets(params)
            results = []
            for folder_key in targets:
                try:
                    await self._do_sync(folder_key)
                    results.append({"folder": folder_key, "ok": True})
                except Exception as exc:
                    results.append({"folder": folder_key, "ok": False, "error": str(exc)})
            return results

        @dispatcher.method("pull")
        async def _pull(params: dict | None) -> list:
            targets = self._resolve_targets(params)
            results = []
            for folder_key in targets:
                try:
                    await self._do_pull(folder_key)
                    results.append({"folder": folder_key, "ok": True})
                except Exception as exc:
                    results.append({"folder": folder_key, "ok": False, "error": str(exc)})
            return results

        @dispatcher.method("rescan")
        async def _rescan(params: dict | None) -> dict:
            return await self.rescan()

        @dispatcher.method("subscribe")
        async def _subscribe(params: dict | None) -> dict:
            return {"ok": True, "message": "use event stream for subscription"}

        return dispatcher

    def _resolve_targets(self, params: dict | None) -> list[str]:
        if params and "folder" in params:
            folder = params["folder"]
            if folder not in self._transports:
                raise MouiSyncError(f"unknown folder: {folder}")
            return [folder]
        return list(self._transports.keys())


def main():
    parser = argparse.ArgumentParser(prog="moui-sync")
    parser.add_argument("command", choices=["daemon"])
    parser.add_argument("--infrastructure", required=True, type=Path)
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args()

    infrastructure = args.infrastructure.expanduser().resolve()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    daemon = SyncDaemon(infrastructure)
    loop = asyncio.new_event_loop()

    async def run():
        await daemon.start()
        stop_event = asyncio.Event()

        def _handle_signal():
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, _handle_signal)
        loop.add_signal_handler(signal.SIGINT, _handle_signal)

        await stop_event.wait()
        await daemon.stop()

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
