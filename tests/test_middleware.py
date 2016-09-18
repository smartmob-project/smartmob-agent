# -*- coding: utf-8 -*-


import asyncio
import aiohttp
import aiohttp.web
import logging
import pytest
import testfixtures

from aiohttp import web
from smartmob_agent import (
    access_log_middleware,
    echo_request_id,
    inject_request_id,
)
from unittest import mock


class HTTPServer:
    """Run an aiohttp application as an asynchronous context manager."""

    def __init__(self, app, host='0.0.0.0', port=80, loop=None):
        self._app = app
        self._loop = loop or asyncio.get_event_loop()
        self._handler = app.make_handler()
        self._server = None
        self._host = host
        self._port = port

    async def __aenter__(self):
        assert not self._server
        self._server = await self._loop.create_server(
            self._handler, self._host, self._port,
        )

    async def __aexit__(self, *args):
        assert self._server
        self._server.close()
        await self._server.wait_closed()
        await self._app.shutdown()
        await self._handler.finish_connections(1.0)
        await self._app.cleanup()
        self._server = None


@pytest.mark.asyncio
async def test_access_log_success_200(event_loop, unused_tcp_port):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        return aiohttp.web.Response(body=b'...')

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(index_url) as rep:
                assert rep.status == 200
                request_id = rep.headers['x-request-id']
                assert request_id
                body = await rep.read()
                assert body == b'...'

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=200,
        duration=1.0,
        request=request_id,
        **{'@timestamp': mock.ANY}
    )


@pytest.mark.parametrize('status', [
    201,
    204,
    302,
])
@pytest.mark.asyncio
async def test_access_log_success_other(status, event_loop, unused_tcp_port):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        return aiohttp.web.Response(status=status, body=b'')

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(index_url, allow_redirects=False) as rep:
                assert rep.status == status
                request_id = rep.headers['x-request-id']
                assert request_id
                body = await rep.read()
                assert body == b''

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=status,
        duration=1.0,
        request=request_id,
        **{'@timestamp': mock.ANY}
    )


@pytest.mark.parametrize('exc_class,expected_status', [
    (web.HTTPBadRequest, 400),
    (web.HTTPNotFound, 404),
    (web.HTTPConflict, 409),
])
@pytest.mark.asyncio
async def test_access_log_failure_http_exception(exc_class, expected_status,
                                                 event_loop, unused_tcp_port):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        raise exc_class(body=b'...')

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(index_url) as rep:
                assert rep.status == expected_status
                request_id = rep.headers['x-request-id']
                assert request_id
                body = await rep.read()
                assert body == b'...'

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=expected_status,
        duration=1.0,
        request=request_id,
        **{'@timestamp': mock.ANY}
    )


@pytest.mark.parametrize('exc_class', [
    ValueError,
    OSError,
    KeyError,
])
@pytest.mark.asyncio
async def test_access_log_failure_other_exception(exc_class, event_loop,
                                                  unused_tcp_port):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        raise exc_class()

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        with testfixtures.LogCapture(level=logging.WARNING) as capture:
            index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
            async with aiohttp.ClientSession(loop=event_loop) as client:
                async with client.get(index_url) as rep:
                    assert rep.status == 500
                    # request_id = rep.headers['x-request-id']
                    # assert request_id
                    body = await rep.read()
                    assert body  # HTML content.
        capture.check(('aiohttp.web', 'ERROR', mock.ANY))

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=500,
        duration=1.0,
        request=mock.ANY,  # aiohttp doesn't seem to execute our signal...
        **{'@timestamp': mock.ANY}
    )


@pytest.mark.asyncio
async def test_access_log_custom_request_id(event_loop, unused_tcp_port):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    request_id = 'My very own request ID!'

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        return aiohttp.web.Response(body=b'...')

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
        async with aiohttp.ClientSession(loop=event_loop) as client:
            head = {
                'X-Request-Id': request_id
            }
            async with client.get(index_url, headers=head) as rep:
                assert rep.status == 200
                assert rep.headers['x-request-id'] == request_id
                body = await rep.read()
                assert body == b'...'

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=200,
        duration=1.0,
        request=request_id,
        **{'@timestamp': mock.ANY}
    )


@pytest.mark.asyncio
async def test_access_log_no_signal(event_loop, unused_tcp_port):
    """Middleware doesn't cause side-effects when misused."""
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]

    app = aiohttp.web.Application(
        loop=event_loop,
        middlewares=[
            inject_request_id,
            access_log_middleware,
        ],
    )
    # Suppose someone forgot to register the signal handler.
    # app.on_response_prepare.append(echo_request_id)
    app['smartmob.event_log'] = event_log
    app['smartmob.clock'] = clock

    async def index(request):
        return aiohttp.web.Response(body=b'...')

    app.router.add_route('GET', '/', index)

    # Given the server is running.
    async with HTTPServer(app, '127.0.0.1', unused_tcp_port):

        # When I access the index.
        index_url = 'http://127.0.0.1:%d' % (unused_tcp_port,)
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(index_url) as rep:
                assert rep.status == 200
                assert 'x-request-id' not in rep.headers
                body = await rep.read()
                assert body == b'...'

    # Then the request is logged in the access log.
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=200,
        duration=1.0,
        request=mock.ANY,  # Not echoed in response, so value doesn't matter.
        **{'@timestamp': mock.ANY}
    )
