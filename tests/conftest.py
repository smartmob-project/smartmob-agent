# -*- coding: utf-8 -*-

import aiohttp
import aiohttp.web
import asyncio
import contextlib
import functools
import os
import os.path
import pytest
import shutil
import structlog
import random
import tempfile
import unittest.mock
import urllib.parse

from smartmob_agent import autoclose, responder
from unittest import mock

__here__ = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope='function')
def event_log():
    return mock.MagicMock(autospec=structlog.get_logger())


@pytest.yield_fixture
def server(event_loop, event_log):
    with responder(event_loop=event_loop,
                   event_log=event_log) as (endpoint, app, handler, server):
        yield endpoint


@pytest.yield_fixture
def client(event_loop):
    session = aiohttp.ClientSession(loop=event_loop)
    with autoclose(session):
        yield session


class FileServer(object):
    def __init__(self, endpoint, root):
        self._endpoint = endpoint
        self._root = root

    @property
    def endpoint(self):
        return self._endpoint

    def url(self, name):
        return urllib.parse.urljoin(self._endpoint, name)

    def provide(self, name, data=None):
        if name:
            path = os.path.join(self._root, name)
        else:
            path = tempfile.mktemp(dir=self._root)
        if data is None:
            return path
        if not isinstance(data, str):
            data = data.read()
        with open(path, 'w') as stream:
            stream.write(data)


@pytest.yield_fixture
def file_server(event_loop, temp_folder):
    host = '127.0.0.1'
    port = 8081
    app = aiohttp.web.Application(loop=event_loop)
    app.router.add_static(
        '/', temp_folder,
    )
    handler = app.make_handler()
    server = event_loop.run_until_complete(event_loop.create_server(
        handler, host, port,
    ))
    yield FileServer('http://%s:%d/' % (host, port), temp_folder)
    server.close()
    event_loop.run_until_complete(server.wait_closed())
    event_loop.run_until_complete(handler.finish_connections(1.0))
    event_loop.run_until_complete(app.finish())


@pytest.yield_fixture
def mktemp():
    """py.test fixture that generates a file name and erases it later."""
    files = []
    def _():
        path = tempfile.mktemp()
        files.append(path)
        return path
    yield _
    # Delete all temporary files.
    for path in files:
        if os.path.isdir(path):
            os.unlink(path)


@pytest.yield_fixture
def temp_folder():
    """py.test fixture that creates a temporary folder."""
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path)


class MockSubprocess(object):
    """Mock implementation of asyncio ``Popen`` object."""

    def __init__(self, args, kwds):
        self._kwds = kwds
        #
        self.pid = random.randint(1, 9999)
        self.stdout = asyncio.StreamReader()
        #
        self._future = asyncio.Future()
        self._killed = False

    @property
    def env(self):
        """Retrieve the environment variables passed to the process."""
        return {k: v for k, v in self._kwds['env'].items()}

    # TODO: not sure what this should do!
    @asyncio.coroutine
    def communicate(self, input=None):
        yield from self._future
        return '', ''

    def wait(self):
        """Wait until the process completes."""
        return self._future

    def mock_complete(self, exit_code=0):
        if not self._future.done():
            self._future.set_result(exit_code)

    def kill(self):
        if self._future.done():
            raise ProcessLookupError
        # Defer completion (as IRL).
        loop = asyncio.get_event_loop()
        loop.call_soon(self._future.set_result, -9)


class MockSubprocessFactory(object):
    def __init__(self):
        self._instances = []

    @property
    def instances(self):
        return self._instances[:]

    @property
    def last_instance(self):
        return self._instances[-1]


@pytest.yield_fixture
def subprocess_factory():
    """Fixture to mock asyncio subprocess creation.

    Each time ``asyncio.create_subprocess_exec`` is called, a future that
    resolves to a ``MockSubprocess`` object will be returned.

    """

    factory = MockSubprocessFactory()

    @functools.wraps(asyncio.create_subprocess_exec)
    def create_subprocess_exec(*args, **kwds):
        p = MockSubprocess(args, kwds)
        f = asyncio.Future()
        f.set_result(p)
        factory._instances.append(p)
        return f

    with unittest.mock.patch('asyncio.create_subprocess_exec') as spawn:
        spawn.side_effect = create_subprocess_exec
        yield factory
