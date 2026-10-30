import pytest
from shapes.corpus.engine import capabilities
from shapes.corpus.engine.errors import CapabilityError

TABLE = {"capabilities": {
    "local.echo": {"run": ["echo", "hi"], "reads": "stdin", "emits": "stdout"},
    "engine.stamp": {"builtin": True},
}}

FLOW = {"pipeline": [
    {"id": "stamp", "uses": "engine.stamp"},
    {"id": "normalize", "uses": {"dispatch_on": "mime", "routes": {
        "text/plain": "local.echo", "text/markdown": "engine.passthrough"}}},
]}


def test_load_table_missing_file_throws(tmp_path):
    with pytest.raises(CapabilityError):
        capabilities.load_table(tmp_path)


def test_load_table_reads_and_validates(tmp_path):
    (tmp_path / "capabilities.yaml").write_text(
        "capabilities:\n  local.echo: {run: [echo], reads: stdin, emits: stdout}\n")
    table = capabilities.load_table(tmp_path)
    assert table["capabilities"]["local.echo"]["emits"] == "stdout"


def test_names_used_includes_dispatch_routes():
    assert capabilities.names_used(FLOW) == {
        "engine.stamp", "local.echo", "engine.passthrough"}


def test_verify_passes_when_all_bound():
    builtins = {"engine.stamp", "engine.passthrough"}
    capabilities.verify(FLOW, TABLE, builtins)  # no raise


def test_verify_names_the_unbound():
    with pytest.raises(CapabilityError, match="local.echo"):
        capabilities.verify(FLOW, {"capabilities": {}}, {"engine.stamp", "engine.passthrough"})


def test_verify_names_the_missing_binary():
    table = {"capabilities": {"local.gone": {
        "run": ["definitely-not-a-binary-7f3a"], "reads": "stdin", "emits": "stdout"}}}
    flow = {"pipeline": [{"id": "x", "uses": "local.gone"}]}
    with pytest.raises(CapabilityError, match="definitely-not-a-binary-7f3a"):
        capabilities.verify(flow, table, set())


def test_resolve_unknown_throws():
    with pytest.raises(CapabilityError):
        capabilities.resolve("local.nope", TABLE)


def test_verify_names_transcript_binding_without_output():
    # plan decision 9: emits: transcript requires ${output} in run: — at startup
    table = {"capabilities": {"local.t": {
        "run": ["sh", "-c", "true"], "reads": "artifact", "emits": "transcript"}}}
    pipeline = {"pipeline": [{"id": "x", "uses": "local.t"}]}
    with pytest.raises(CapabilityError, match="output"):
        capabilities.verify(pipeline, table, set())


def test_resolve_passes_through_stream_binding():
    table = {"capabilities": {"api.claude-json": {"run": ["bin/claude-json"], "stream": ["bin/claude-stream"],
                                                   "reads": "stdin", "emits": "envelope"}}}
    b = capabilities.resolve("api.claude-json", table)
    assert b["stream"] == ["bin/claude-stream"]


def test_resolve_omits_stream_when_absent():
    table = {"capabilities": {"api.claude": {"run": ["claude", "-p"], "reads": "stdin", "emits": "stdout"}}}
    b = capabilities.resolve("api.claude", table)
    assert "stream" not in b
