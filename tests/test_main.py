# -*- coding: utf-8 -*-

import aiohttp
import asyncio
import json
import os
import pytest
import signal
import structlog
import testfixtures

from contextlib import contextmanager
from datetime import datetime
from functools import partial
from freezegun import freeze_time
from itertools import chain
from smartmob_agent import (
    configure_logging,
    FluentLoggerFactory,
    main,
    version,
)
from unittest import mock


@contextmanager
def setenv(env):
    old_env = os.environ
    new_env = dict(chain(os.environ.items(), env.items()))
    os.environ = new_env
    try:
        yield
    finally:
        os.environ = old_env


def test_configure_logging_stdout(capsys):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format='kv',
            utc=False,
            endpoint='file:///dev/stdout',
        )
        log = structlog.get_logger()
        log.info('teh.event', a=1)
    out, err = capsys.readouterr()
    assert err == ""
    assert out == "@timestamp='2016-05-08T21:19:00' event='teh.event' a=1\n"


def test_configure_logging_stderr(capsys):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format='kv',
            utc=False,
            endpoint='file:///dev/stderr',
        )
        log = structlog.get_logger()
        log.info('teh.event', a=1)
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "@timestamp='2016-05-08T21:19:00' event='teh.event' a=1\n"


def test_configure_logging_file(capsys, tempdir):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format='kv',
            utc=False,
            endpoint='file://./gitmesh.log',
        )
        log = structlog.get_logger()
        log.info('teh.event', a=1)
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""
    with open('./gitmesh.log', 'r') as stream:
        logs = stream.read()
    assert logs == "@timestamp='2016-05-08T21:19:00' event='teh.event' a=1\n"


def test_configure_logging_unknown_scheme(capsys, tempdir):
    with pytest.raises(ValueError) as error:
        configure_logging(
            log_format='kv',
            utc=False,
            endpoint='flume://127.0.0.1:44444',
        )
        log = structlog.get_logger()
        log.info('teh.event', a=1)
    assert str(error.value) == \
        'Invalid logging endpoint "flume://127.0.0.1:44444".'


@pytest.mark.parametrize('log_format,expected', [
    ('kv', "@timestamp='2016-05-08T21:19:00' event='teh.event' a=1 b=2"),
    ('json', ('{"@timestamp": "2016-05-08T21:19:00"'
              ', "a": 1, "b": 2, "event": "teh.event"}')),
])
def test_log_format(log_format, expected):
    with freeze_time("2016-05-08 21:19:00"):
        with testfixtures.OutputCapture() as capture:
            configure_logging(
                log_format=log_format,
                utc=False,
                endpoint='file:///dev/stderr',
            )
            log = structlog.get_logger()
            log.info('teh.event', a=1, b=2)
        capture.compare(expected)


@pytest.mark.parametrize('url,host,port,app', [
    ('fluent://127.0.0.1:24224/the-app', '127.0.0.1', 24224, 'the-app'),
    ('fluent://127.0.0.1/the-app', '127.0.0.1', 24224, 'the-app'),
    ('fluent://127.0.0.1/', '127.0.0.1', 24224, ''),
])
def test_fluent_url_parser(url, host, port, app):
    factory = FluentLoggerFactory.from_url(url)
    assert factory.host == host
    assert factory.port == port
    assert factory.app == app


@pytest.mark.parametrize('url', [
    'fluent://127.0.0.1:abcd/the-app',
    'fluentd://127.0.0.1:abcd/the-app',  # typo in scheme.
    'fluent://127.0.0.1:24224/the-app?hello=1',  # query strings not allowed.
])
def test_fluent_url_parser_invalid_url(url):
    with pytest.raises(ValueError) as error:
        print(FluentLoggerFactory.from_url(url))
    assert str(error.value) == \
        'Invalid URL: "%s".' % (url,)


@pytest.mark.parametrize('logging_endpoint,utc,expected_timestamp', [
    ('fluent://127.0.0.1:24224/the-app', True, '2016-05-08T21:19:00+00:00'),
    ('fluent://127.0.0.1:24224/the-app', False, '2016-05-08T21:19:00'),
])
@mock.patch('fluent.sender.FluentSender.emit')
def test_logging_fluentd(emit, logging_endpoint, utc, expected_timestamp):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format='kv',  # Ignored!
            utc=utc,
            endpoint=logging_endpoint,
        )
        log = structlog.get_logger()
        with testfixtures.OutputCapture() as capture:
            log.info('teh.event', a=1, b=2)
        capture.compare('')
        emit.assert_called_once_with('teh.event', {
            'a': 1,
            'b': 2,
            '@timestamp': expected_timestamp,
        })


@mock.patch('sys.argv', ['smartmob-agent', '--version'])
def test_main_sys_argv(capsys):
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version


def test_main_explicit_args(capsys):
    with pytest.raises(SystemExit) as error:
        main(['--version'])
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version


def test_main_ctrl_c(capsys, event_loop):

    # ...
    @asyncio.coroutine
    def fetch_http(url):
        client = aiohttp.ClientSession(loop=event_loop)
        response = yield from client.get(url)
        assert response.status == 200
        body = yield from response.read()
        body = body.strip()
        client.close()
        return body

    def forward(target, source):
        try:
            target.set_result(source.result())
        except Exception as error:
            target.set_exception(error)

    def hello_http(f):
        t = event_loop.create_task(fetch_http('http://127.0.0.1:8080'))
        t.add_done_callback(partial(forward, f))

    # Automatically trigger CTRL-C after the test queries have run.
    f = asyncio.Future()
    event_loop.call_later(0.5, hello_http, f)
    event_loop.call_later(0.6, os.kill, os.getpid(), signal.SIGINT)

    # Run the main function.
    event_log = mock.MagicMock()
    with mock.patch('structlog.get_logger') as get_logger:
        get_logger.return_value = event_log
        main([])

    # Error log should be empty.
    stdout, stderr = capsys.readouterr()
    assert stderr.strip() == ''
    assert stdout.strip() == ''

    # Structured event log should show the CTRL-C request.
    event_log.info.assert_has_calls([
        mock.call('bind', transport='tcp', host='0.0.0.0', port=8080),
        mock.call(
            'http.access', path='/', outcome=200,
            duration=mock.ANY, request=mock.ANY,
            **{'@timestamp': mock.ANY}
        ),
        mock.call('stop', reason='ctrl-c'),
    ])

    # Body should match!
    assert json.loads(f.result().decode('utf-8'))


def test_main_fluent_logging_endpoint(capsys, event_loop, fluent_server):

    async def fetch_http(url):
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(url) as response:
                assert response.status == 200
                body = await response.read()
                body = body.strip()
        return body

    def forward(target, source):
        try:
            target.set_result(source.result())
        except Exception as error:
            target.set_exception(error)

    def hello_http(f):
        t = event_loop.create_task(fetch_http('http://127.0.0.1:8080'))
        t.add_done_callback(partial(forward, f))

    # Automatically trigger CTRL-C after the test queries have run.
    f = asyncio.Future()
    event_loop.call_later(0.5, hello_http, f)
    event_loop.call_later(0.6, os.kill, os.getpid(), signal.SIGINT)

    # Run the main function.
    main([
        '--logging-endpoint=fluent://%s:%d/smartmob-agent' % (
            fluent_server[0],
            fluent_server[1],
        ),
    ])

    # Error log should be empty.
    stdout, stderr = capsys.readouterr()
    assert stderr.strip() == ''
    assert stdout.strip() == ''

    # Git hook logs will be sent to our mock FluentD server.
    assert len(fluent_server[2]) > 0

    # Body should match!
    assert json.loads(f.result().decode('utf-8'))


def test_main_fluent_logging_endpoint_env(capsys, event_loop, fluent_server):

    async def fetch_http(url):
        async with aiohttp.ClientSession(loop=event_loop) as client:
            async with client.get(url) as response:
                assert response.status == 200
                body = await response.read()
                body = body.strip()
        return body

    def forward(target, source):
        try:
            target.set_result(source.result())
        except Exception as error:
            target.set_exception(error)

    def hello_http(f):
        t = event_loop.create_task(fetch_http('http://127.0.0.1:8080'))
        t.add_done_callback(partial(forward, f))

    # Automatically trigger CTRL-C after the test queries have run.
    f = asyncio.Future()
    event_loop.call_later(0.5, hello_http, f)
    event_loop.call_later(0.6, os.kill, os.getpid(), signal.SIGINT)

    # Run the main function.
    env = {
        'SMARTMOB_LOGGING_ENDPOINT': 'fluent://%s:%d/smartmob-agent' % (
            fluent_server[0],
            fluent_server[1],
        ),
    }
    with setenv(env):
        main([])

    # Error log should be empty.
    stdout, stderr = capsys.readouterr()
    assert stderr.strip() == ''
    assert stdout.strip() == ''

    # Git hook logs will be sent to our mock FluentD server.
    assert len(fluent_server[2]) > 0

    # Body should match!
    assert json.loads(f.result().decode('utf-8'))


@pytest.mark.parametrize('timestamp,expected_timestamp', [
    ('2016-05-08T21:19:00', '2016-05-08T21:19:00'),
    (datetime(2016, 5, 8, 21, 19, 0), '2016-05-08T21:19:00'),
])
@mock.patch('fluent.sender.FluentSender.emit')
def test_logging_fluentd_override_timestamp(emit, timestamp,
                                            expected_timestamp):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format='kv',  # Ignored!
            utc=False,
            endpoint='fluent://127.0.0.1:24224/the-app',
        )
        log = structlog.get_logger()
        with testfixtures.OutputCapture() as capture:
            log.info('teh.event', a=1, b=2, **{'@timestamp': timestamp})
        capture.compare('')
        emit.assert_called_once_with('teh.event', {
            'a': 1,
            'b': 2,
            '@timestamp': expected_timestamp,
        })
