import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from pathlib import Path

from cli.sync.encryption.none_layer import NoneEncryptionLayer
from cli.sync.encryption.age_ssh_layer import AgeSSHEncryptionLayer


def _generate_test_keypair() -> tuple[str, bytes]:
    private_key = Ed25519PrivateKey.generate()
    pub_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    priv_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    return pub_bytes.decode(), priv_bytes


@pytest.fixture
def test_keypair():
    return _generate_test_keypair()


@pytest.fixture
def encryption_folder(tmp_path):
    (tmp_path / "notes.md").write_text("secret notes")
    (tmp_path / "data.yaml").write_text("key: value")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep content")
    return tmp_path


class TestNoneLayer:
    def test_encrypt_is_noop(self, encryption_folder):
        layer = NoneEncryptionLayer()
        result = layer.encrypt_tree(encryption_folder, [".md", ".yaml"])
        assert result == []
        age_files = list(encryption_folder.rglob("*.age"))
        assert age_files == []

    def test_decrypt_is_noop(self, encryption_folder):
        layer = NoneEncryptionLayer()
        result = layer.decrypt_tree(encryption_folder)
        assert result == []


class TestAgeSSHLayer:
    def test_encrypt_creates_age_files(self, test_keypair, encryption_folder):
        pub_key, _ = test_keypair
        layer = AgeSSHEncryptionLayer(recipients=[pub_key])
        created = layer.encrypt_tree(encryption_folder, [".md", ".yaml"])
        assert len(created) == 2
        assert all(p.suffix == ".age" for p in created)
        assert (encryption_folder / "notes.md.age").exists()
        assert (encryption_folder / "data.yaml.age").exists()

    def test_ciphertext_differs_from_plaintext(self, test_keypair, encryption_folder):
        pub_key, _ = test_keypair
        layer = AgeSSHEncryptionLayer(recipients=[pub_key])
        original = (encryption_folder / "notes.md").read_bytes()
        layer.encrypt_tree(encryption_folder, [".md"])
        ciphertext = (encryption_folder / "notes.md.age").read_bytes()
        assert ciphertext != original

    def test_round_trip(self, test_keypair, encryption_folder):
        pub_key, priv_pem = test_keypair
        layer = AgeSSHEncryptionLayer(recipients=[pub_key])

        # Save original content
        originals = {
            "notes.md": (encryption_folder / "notes.md").read_text(),
            "data.yaml": (encryption_folder / "data.yaml").read_text(),
            "sub/deep.txt": (encryption_folder / "sub" / "deep.txt").read_text(),
        }

        # Encrypt all extensions
        layer.encrypt_tree(encryption_folder, [".md", ".yaml", ".txt"])

        # Delete plaintext files
        for name in originals:
            (encryption_folder / name).unlink()

        # Decrypt with key
        decrypted = layer.decrypt_tree_with_key(encryption_folder, priv_pem)
        assert len(decrypted) == 3

        # Verify content matches
        for name, content in originals.items():
            assert (encryption_folder / name).read_text() == content

    def test_orphan_cleanup(self, test_keypair, encryption_folder):
        pub_key, priv_pem = test_keypair
        layer = AgeSSHEncryptionLayer(recipients=[pub_key])

        # Encrypt
        layer.encrypt_tree(encryption_folder, [".md", ".yaml", ".txt"])

        # Delete plaintext
        (encryption_folder / "notes.md").unlink()
        (encryption_folder / "data.yaml").unlink()
        (encryption_folder / "sub" / "deep.txt").unlink()

        # Simulate removing an .age file (as if it was deleted from remote)
        (encryption_folder / "data.yaml.age").unlink()

        # Decrypt — should restore notes.md and deep.txt but NOT data.yaml
        decrypted = layer.decrypt_tree_with_key(encryption_folder, priv_pem)

        assert (encryption_folder / "notes.md").exists()
        assert (encryption_folder / "sub" / "deep.txt").exists()
        # data.yaml was orphaned (no .age counterpart) so it should not exist
        assert not (encryption_folder / "data.yaml").exists()
