# -*- coding: utf-8 -*-


import pytest

from aiohttp import web
from smartmob_agent import access_log_middleware
from unittest import mock


@pytest.mark.asyncio
async def test_middleware_success_200():
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]
    app = {
        'smartmob.event_log': event_log,
        'smartmob.clock': clock,
    }

    req = mock.MagicMock()
    req.path = '/'
    rep = web.Response(body=b'...')

    async def index(request):
        assert request is req
        return rep

    handler = await access_log_middleware(app, index)
    response = await handler(req)

    assert response is rep
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=200,
        duration=1.0,
    )


@pytest.mark.parametrize('status', [
    201,
    204,
    302,
])
@pytest.mark.asyncio
async def test_middleware_success_other(status):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]
    app = {
        'smartmob.event_log': event_log,
        'smartmob.clock': clock,
    }

    req = mock.MagicMock()
    req.path = '/'
    rep = web.Response(body=b'...', status=status)

    async def index(request):
        assert request is req
        return rep

    handler = await access_log_middleware(app, index)
    response = await handler(req)

    assert response is rep
    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=status,
        duration=1.0,
    )


@pytest.mark.parametrize('exc_class,expected_status', [
    (web.HTTPBadRequest, 400),
    (web.HTTPNotFound, 404),
    (web.HTTPConflict, 409),
])
@pytest.mark.asyncio
async def test_middleware_failure_http_exception(exc_class, expected_status):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]
    app = {
        'smartmob.event_log': event_log,
        'smartmob.clock': clock,
    }

    req = mock.MagicMock()
    req.path = '/'

    async def index(request):
        assert request is req
        raise exc_class

    handler = await access_log_middleware(app, index)
    with pytest.raises(exc_class):
        print(await handler(req))

    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=expected_status,
        duration=1.0,
    )


@pytest.mark.parametrize('exc_class', [
    ValueError,
    OSError,
    KeyError,
])
@pytest.mark.asyncio
async def test_middleware_failure_http_exception(exc_class):
    event_log = mock.MagicMock()
    clock = mock.MagicMock()
    clock.side_effect = [0.0, 1.0]
    app = {
        'smartmob.event_log': event_log,
        'smartmob.clock': clock,
    }

    req = mock.MagicMock()
    req.path = '/'

    async def index(request):
        assert request is req
        raise exc_class

    handler = await access_log_middleware(app, index)
    with pytest.raises(exc_class):
        print(await handler(req))

    event_log.info.assert_called_once_with(
        'http.access',
        path='/',
        outcome=500,
        duration=1.0,
    )
