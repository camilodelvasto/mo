import re
from cli.sync.ulid_id import generate_ulid

CROCKFORD_RE = re.compile(r"^[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{26}$")


def test_returns_string():
    assert isinstance(generate_ulid(), str)


def test_length_is_26():
    assert len(generate_ulid()) == 26


def test_successive_calls_are_unique():
    a = generate_ulid()
    b = generate_ulid()
    assert a != b


def test_valid_crockford_base32():
    assert CROCKFORD_RE.match(generate_ulid())
