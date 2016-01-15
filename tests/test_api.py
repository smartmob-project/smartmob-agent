# -*- coding: utf-8 -*-

import asyncio
import json
import pytest

from smartmob_agent import start_responder

@asyncio.coroutine
def get_json(client, url):
    response = yield from client.get(url)
    body = yield from response.read()
    return response, json.loads(body.decode('utf-8'))

@asyncio.coroutine
def post_json(client, url, payload):
    response = yield from client.post(url, data=json.dumps(payload))
    body = yield from response.read()
    return response, json.loads(body.decode('utf-8'))

@pytest.mark.asyncio
def test_simple_flow(event_loop, server, client):
    """Follows links in REST API."""

    # Start a new session.
    response, index = yield from get_json(
        client, 'http://127.0.0.1:8080',
    )
    assert response.status == 200
    assert index['create']

    # Listing should be empty.
    response, listing = yield from get_json(
        client, index['list'],
    )
    assert response.status == 200
    assert listing == {
        'processes': [],
    }

    # Cannot create a process without required fields.
    response = yield from client.post(
        index['create'], data=json.dumps({
            'source_url': 'http://...',
            'process_type': 'web',
        }).encode('utf-8'),
    )
    assert response.status == 400
    yield from response.read()

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'foo',
            'node': 'web.0',
            'source_url': 'http://...',
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'foo'
    assert process['slug']
    assert process['details'] == response.headers['Location']

    # Cannot create the same one again.
    response = yield from client.post(
        index['create'], data=json.dumps({
            'app': 'foo',
            'node': 'web.0',
            'source_url': 'http://...',
            'process_type': 'web',
        }).encode('utf-8'),
    )
    assert response.status == 409
    yield from response.read()

    # Get the process details.
    response, process2 = yield from get_json(
        client,
        process['details'],
    )
    assert response.status == 200
    assert process2 == process

    # Test invalid slug in URL.
    response = yield from client.get(
        process['details'][:-1],  # Intentionally invalid.
    )
    assert response.status == 404
    yield from response.read()

    # Listing should contain our new process.
    response, listing = yield from get_json(
        client, index['list'],
    )
    assert response.status == 200
    assert listing == {
        'processes': [
            process,
        ],
    }

    # Attach console (to stream logs).
    stream = yield from client.ws_connect(
        process['attach']
    )

    # Detach console.
    yield from stream.close()

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}

    # Test invalid slug in URL.
    response = yield from client.post(
        process['delete'][:-1], # Intentionally invalid.
    )
    assert response.status == 404
    yield from response.read()
