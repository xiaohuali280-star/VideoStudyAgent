import os
import socket

import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def application(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "data"))
    yield app
    if hasattr(app.state, "repository"):
        app.state.repository.engine.dispose()


@pytest.fixture(autouse=True)
def isolated_offline_environment(monkeypatch):
    original_connect = socket.socket.connect

    # Windows asyncio uses a loopback socketpair even for in-memory ASGI tests.
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Default backend tests must not use external connections")

    def deny_external_connection(*args, **kwargs):
        raise AssertionError("Default backend tests must not use external connections")

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket, "create_connection", deny_external_connection)
    for key in tuple(os.environ):
        if key.startswith("VSA_"):
            monkeypatch.delenv(key)
