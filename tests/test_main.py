# -*- coding: utf-8 -*-

import aiohttp
import asyncio
import os
import pytest
import signal

from functools import partial
from smartmob_agent import main, version
from unittest import mock

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

    @asyncio.coroutine
    def fetch_ws(url):
        client = aiohttp.ClientSession(loop=event_loop)
        stream = yield from client.ws_connect(url)
        body = yield from stream.receive()
        body = body.data.strip()
        yield from stream.close()
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

    def hello_ws(f):
        t = event_loop.create_task(fetch_ws('ws://127.0.0.1:8080'))
        t.add_done_callback(partial(forward, f))

    # Automatically trigger CTRL-C after the test queries have run.
    f1 = asyncio.Future()
    f2 = asyncio.Future()
    event_loop.call_later(0.5, hello_http, f1)
    event_loop.call_later(0.5, hello_ws, f2)
    event_loop.call_later(0.6, os.kill, os.getpid(), signal.SIGINT)

    # Run the main function.
    main([])

    # Error log should be empty.
    stdout, stderr = capsys.readouterr()
    assert stdout.strip() == ''
    assert stderr.strip() == ''

    # Body should match!
    assert f1.result() == b'hello, world!'
    assert f2.result() == 'hello, world!'
