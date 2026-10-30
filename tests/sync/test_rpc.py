import pytest

from cli.sync.daemon.rpc import PROTOCOL_VERSION, RPCDispatcher


@pytest.mark.asyncio
async def test_dispatch_known_method():
    d = RPCDispatcher()

    @d.method("ping")
    async def ping(params):
        return "pong"

    resp = await d.dispatch({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp["result"] == "pong"
    assert resp["id"] == 1
    assert resp["jsonrpc"] == "2.0"


@pytest.mark.asyncio
async def test_dispatch_unknown_method():
    d = RPCDispatcher()
    resp = await d.dispatch({"jsonrpc": "2.0", "id": 2, "method": "nope"})
    assert resp["error"]["code"] == -32601
    assert resp["id"] == 2


@pytest.mark.asyncio
async def test_dispatch_with_params():
    d = RPCDispatcher()

    @d.method("echo")
    async def echo(params):
        return params

    resp = await d.dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "echo", "params": {"msg": "hi"}}
    )
    assert resp["result"] == {"msg": "hi"}


@pytest.mark.asyncio
async def test_response_includes_version():
    d = RPCDispatcher()

    @d.method("v")
    async def v(params):
        return 1

    success = await d.dispatch({"jsonrpc": "2.0", "id": 4, "method": "v"})
    assert success["version"] == PROTOCOL_VERSION

    error = await d.dispatch({"jsonrpc": "2.0", "id": 5, "method": "missing"})
    assert error["version"] == PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_malformed_request():
    d = RPCDispatcher()
    # missing "method" key
    resp = await d.dispatch({"jsonrpc": "2.0", "id": 6})
    assert resp["error"]["code"] == -32600

    # missing "jsonrpc" key
    resp = await d.dispatch({"id": 7, "method": "x"})
    assert resp["error"]["code"] == -32600
