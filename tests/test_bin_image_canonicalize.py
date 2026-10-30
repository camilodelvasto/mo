# tests/test_bin_image_canonicalize.py
import io
import subprocess
import sys
from pathlib import Path

from PIL import Image

BIN_ONLY = [sys.executable, str(Path("bin/image-canonicalize"))]
BIN = BIN_ONLY + ["--max-edge", "2048", "--quality", "82", "--max-pixels", "40000000"]

def _png_with_exif() -> bytes:
    img = Image.new("RGB", (32, 32), (200, 100, 50))
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0110] = "SecretCameraModel"   # Model tag — must not survive
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()

def test_reencodes_to_webp():
    out = subprocess.run(BIN, input=_png_with_exif(), capture_output=True)
    assert out.returncode == 0, out.stderr
    img = Image.open(io.BytesIO(out.stdout))
    assert img.format == "WEBP"

def test_strips_metadata():
    out = subprocess.run(BIN, input=_png_with_exif(), capture_output=True)
    assert b"SecretCameraModel" not in out.stdout          # the byte string is gone
    img = Image.open(io.BytesIO(out.stdout))
    assert not dict(img.getexif())                          # no EXIF survives

def test_garbage_is_rejected():
    out = subprocess.run(BIN, input=b"this is not an image", capture_output=True)
    assert out.returncode != 0
    assert out.stdout == b""
    assert b"could not decode" in out.stderr.lower()


def _png_claiming(width: int, height: int) -> bytes:
    """A 1x1 PNG whose IHDR claims `width`x`height`: tiny on disk, enormous when
    decoded. Image.open reads the size from IHDR without decoding; load() would try."""
    import struct, zlib
    buf = io.BytesIO(); Image.new("RGB", (1, 1)).save(buf, format="PNG"); raw = buf.getvalue()
    i = raw.index(b"IHDR")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return raw[:i - 4] + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk)) + raw[i + 4 + 13 + 4:]


def test_oversized_pixel_count_is_rejected_before_decoding():
    # A decompression bomb: 8000x8000 = 64 MP claimed by a ~100-byte file — UNDER
    # Pillow's own 178 MP bomb limit (which would still allow ~1 GB across the RGB
    # copies), over the bound this binding declares. Refused from the header, never
    # decoded, in well under the time a decode would take.
    out = subprocess.run(BIN, input=_png_claiming(8_000, 8_000), capture_output=True, timeout=5)
    assert out.returncode != 0
    assert b"64000000 pixels" in out.stderr and b"exceeds" in out.stderr


def test_pixel_bound_admits_a_normal_photo():
    img = Image.new("RGB", (4000, 3000), (10, 20, 30)); buf = io.BytesIO(); img.save(buf, format="JPEG")
    out = subprocess.run(BIN, input=buf.getvalue(), capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert Image.open(io.BytesIO(out.stdout)).size == (2048, 1536)


# --- the canonical bounds are declared on the binding, not buried in the shim -----

def test_bounds_are_binding_arguments():
    img = Image.new("RGB", (900, 600), (7, 8, 9)); buf = io.BytesIO(); img.save(buf, format="JPEG")
    out = subprocess.run(BIN_ONLY + ["--max-edge", "300", "--quality", "60", "--max-pixels", "1000000"],
                         input=buf.getvalue(), capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert Image.open(io.BytesIO(out.stdout)).size == (300, 200)


def test_declared_pixel_bound_is_the_one_enforced():
    out = subprocess.run(BIN + ["--max-pixels", "100"], input=_png_claiming(50, 50),
                         capture_output=True, timeout=5)
    assert out.returncode != 0 and b"2500 pixels" in out.stderr


def test_undeclared_bounds_are_refused_not_defaulted():
    out = subprocess.run(BIN_ONLY, input=b"irrelevant", capture_output=True)
    assert out.returncode == 2 and out.stdout == b""
    for flag in (b"--max-edge", b"--quality", b"--max-pixels"):
        assert flag in out.stderr
