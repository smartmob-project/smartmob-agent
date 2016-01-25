# -*- coding: utf-8 -*-


import pytest

from smartmob_agent import download


@pytest.mark.asyncio
def test_download(file_server, mktemp, client):
    file_server.provide('hello.txt', 'hello, world!')
    path = mktemp()
    content_type = yield from download(
        client, file_server.url('hello.txt'), path,
    )
    assert content_type == 'text/plain'
    with open(path, 'r') as stream:
        assert stream.read() == 'hello, world!'


@pytest.mark.asyncio
def test_download_404(file_server, mktemp, client):
    path = mktemp()
    with pytest.raises(Exception) as error:
        yield from download(
            client, file_server.url('hello.txt'), path,
        )
    assert str(error.value) == 'Download failed.'


@pytest.mark.asyncio
def test_download_reject(file_server, mktemp, client):
    def check_ext(url, response):
        return not url.endswith('.zip')
    
    file_server.provide('hello.txt', 'hello, world!')
    path = mktemp()
    with pytest.raises(Exception) as error:
        yield from download(
            client, file_server.url('hello.txt'), path, reject=check_ext,
        )
    assert str(error.value) == 'Download rejected.'
