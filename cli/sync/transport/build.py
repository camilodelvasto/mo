from cli.sync.config import SyncDeclaration
from cli.sync.encryption.age_ssh_layer import AgeSSHEncryptionLayer
from cli.sync.errors import UnknownAdapterError
from cli.sync.transport.base import Transport
from cli.sync.transport.encryption_wrapper import EncryptionWrapper


def build_transport(declaration: SyncDeclaration, remote_cfg: dict) -> Transport:
    adapter_type = remote_cfg.get("adapter")
    if adapter_type != "git_sync":
        raise UnknownAdapterError(f"unknown adapter: {adapter_type!r}")

    from shapes.shared.adapters.git_sync import GitSyncAdapter

    base = GitSyncAdapter(remote_cfg)

    match declaration.encryption.type:
        case "none":
            return base
        case "age-ssh":
            layer = AgeSSHEncryptionLayer(declaration.encryption.recipients)
            extensions = [".yaml", ".yml", ".json", ".jsonl", ".md", ".txt", ".csv"]
            return EncryptionWrapper(
                inner=base,
                encryption_layer=layer,
                extensions=extensions,
            )
