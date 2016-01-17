# -*- coding: utf-8 -*-

import aiohttp
import pytest

from smartmob_agent import start_responder

@pytest.yield_fixture
def server(event_loop):
    app, handler, server = event_loop.run_until_complete(
        start_responder(loop=event_loop)
    )
    yield
    server.close()
    event_loop.run_until_complete(server.wait_closed())
    event_loop.run_until_complete(handler.finish_connections(1.0))
    event_loop.run_until_complete(app.finish())

@pytest.yield_fixture
def client(event_loop):
    session = aiohttp.ClientSession(loop=event_loop)
    yield session
    session.close()
