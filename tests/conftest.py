# -*- coding: utf-8 -*-

import aiohttp
import aiohttp.web
import aiotk
import asyncio
import functools
import msgpack
import os
import os.path
import pytest
import shutil
import structlog
import random
import tempfile
import testfixtures
import timeit
import unittest.mock
import urllib.parse

from smartmob_agent import (
    access_log_middleware,
    autoclose,
    configure_logging,
    echo_request_id,
    inject_request_id,
    responder,
)
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
def file_server(event_loop, temp_folder, event_log):
    host = '127.0.0.1'
    port = 8081
    app = aiohttp.web.Application(loop=event_loop, middlewares=[
        inject_request_id,
        access_log_middleware,
    ])
    app.on_response_prepare.append(echo_request_id)
    app.router.add_static(
        '/', temp_folder,
    )
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = timeit.default_timer
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


@pytest.yield_fixture(scope='function')
def tempdir():
    old_cwd = os.getcwd()
    with testfixtures.TempDirectory(create=True) as directory:
        os.chdir(directory.path)
        yield
        os.chdir(old_cwd)
        directory.cleanup()


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


@pytest.fixture(scope='function', autouse=True)
def logging():
    """Setup default logging for tests.

    Tests can reconfigure logging if they wish to.
    """
    configure_logging(
        log_format='kv',
        utc=False,
        endpoint='file:///dev/stdout',
    )


async def service_fluent_client(records, reader, writer):
    """TCP handler for mock FluentD server.

    See:
    - https://github.com/fluent/fluentd/wiki/Forward-Protocol-Specification-v0
    - https://pythonhosted.org/msgpack-python/api.html#msgpack.Unpacker
    """
    unpacker = msgpack.Unpacker()
    data = await reader.read(1024)
    while data:
        unpacker.feed(data)
        for record in unpacker:
            records.append(record)
        data = await reader.read(1024)


@pytest.yield_fixture(scope='function')
def fluent_server(event_loop, unused_tcp_port):
    """Mock FluentD server."""

    records = []

    # TODO: provide a built-in means to pass in shared server state as this
    #       wrapper will probably not cancel cleanly.
    async def service_connection(reader, writer):
        return await service_fluent_client(records, reader, writer)

    # Serve connections.
    host, port = ('127.0.0.1', unused_tcp_port)
    server = aiotk.TCPServer(host, port, service_connection)
    server.start()
    event_loop.run_until_complete(server.wait_started())
    yield host, port, records
    server.close()
    event_loop.run_until_complete(server.wait_closed())
