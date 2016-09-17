# -*- coding: utf-8 -*-

import aiohttp
import asyncio
import json
import os
import pytest
import signal
import structlog
import testfixtures

from functools import partial
from freezegun import freeze_time
from smartmob_agent import (
    configure_logging,
    main,
    version,
)
from unittest import mock


@pytest.mark.parametrize('log_format,expected', [
    ('kv', "@timestamp='2016-05-08T21:19:00' event='teh.event' a=1 b=2"),
    ('json', ('{"@timestamp": "2016-05-08T21:19:00"'
              ', "a": 1, "b": 2, "event": "teh.event"}')),
])
def test_log_format(log_format, expected):
    with freeze_time("2016-05-08 21:19:00"):
        configure_logging(
            log_format=log_format,
            utc=False,
        )
        log = structlog.get_logger()
        with testfixtures.OutputCapture() as capture:
            log.info('teh.event', a=1, b=2)
        capture.compare(expected)


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
        ),
        mock.call('stop', reason='ctrl-c'),
    ])

    # Body should match!
    assert json.loads(f.result().decode('utf-8'))
