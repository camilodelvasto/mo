"""Pydantic models for sync declarations and device state."""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from ruamel.yaml import YAML

from cli.sync.errors import ConfigValidationError, UnsupportedVersionError
from cli.sync.ulid_id import generate_ulid

SUPPORTED_VERSION = 1

_yaml = YAML()
_yaml.preserve_quotes = True


# ── Sync declaration (infrastructure/syncs/<path>.yaml) ──────────


class EncryptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "age-ssh"]
    recipients: list[str] = []

    @model_validator(mode="after")
    def _age_ssh_requires_recipients(self) -> EncryptionConfig:
        if self.type == "age-ssh" and not self.recipients:
            raise ValueError("age-ssh encryption requires at least one recipient")
        return self


class SyncSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debounce_seconds: int = 10
    max_debounce_seconds: int = 60
    pull_interval_seconds: int = 60


class SyncDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    target: str
    remote: str
    encryption: EncryptionConfig
    sync: SyncSettings | None = None

    @model_validator(mode="after")
    def _check_version(self) -> SyncDeclaration:
        if self.version != SUPPORTED_VERSION:
            raise UnsupportedVersionError(
                f"sync declaration version {self.version} not supported "
                f"(expected {SUPPORTED_VERSION})"
            )
        return self


# ── Device state (~/.config/moui/sync/state.yaml) ────────────────


class DeviceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str


class FolderOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debounce_seconds: int | None = None


class DeviceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    device: DeviceIdentity = None
    overrides: dict[str, FolderOverride] = {}

    @model_validator(mode="before")
    @classmethod
    def _fill_device_defaults(cls, data):
        if isinstance(data, dict) and data.get("device") is None:
            data["device"] = {
                "id": generate_ulid(),
                "display_name": platform.node(),
            }
        return data


# ── Loaders ──────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        data = _yaml.load(f)
    if not isinstance(data, dict):
        raise ConfigValidationError(f"{path} did not parse as a YAML mapping")
    return data


def load_sync_declaration(path: Path) -> SyncDeclaration:
    data = _load_yaml(path)
    try:
        return SyncDeclaration(**data)
    except UnsupportedVersionError:
        raise
    except Exception as exc:
        raise ConfigValidationError(str(exc)) from exc


def load_device_state(path: Path) -> DeviceState:
    if not path.exists():
        return DeviceState()
    data = _load_yaml(path)
    try:
        return DeviceState(**data)
    except Exception as exc:
        raise ConfigValidationError(str(exc)) from exc


def write_sync_declaration(path: Path, decl: SyncDeclaration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        _yaml.dump(decl.model_dump(exclude_none=True), f)


def write_device_state(path: Path, state: DeviceState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        _yaml.dump(state.model_dump(exclude_none=True), f)
