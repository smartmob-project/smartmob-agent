# -*- coding: utf-8 -*-


import aiohttp
import asyncio
import json
import pytest
import urllib.parse
import zipfile

from smartmob_agent import autoclose
from unittest import mock


@asyncio.coroutine
def get_json(client, url):
    response = yield from client.get(url)
    with autoclose(response):
        body = yield from response.read()
        return response, json.loads(body.decode('utf-8'))


@asyncio.coroutine
def post_json(client, url, payload):
    response = yield from client.post(url, data=json.dumps(payload))
    with autoclose(response):
        body = yield from response.read()
        return response, json.loads(body.decode('utf-8'))


@pytest.mark.asyncio
def test_full_flow(event_loop, server, client, file_server, event_log):
    """Follows links in REST API."""

    # Create an application.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'web: python dots.py')
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
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

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'foo',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'foo'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process.pop('state') == 'pending'
    event_log.info.assert_has_calls([mock.call(
        'process.create',
        app='foo',
        node='web.0',
        slug='foo.web.0',
    )])

    # Get the process details.
    response, process2 = yield from get_json(
        client,
        process['details'],
    )
    assert response.status == 200
    assert process2['app'] == 'foo'
    assert process2.pop('state') == 'downloading'

    # Listing should contain our new process.
    #
    # NOTE: state here is unpredictable and flaky.
    response, listing = yield from get_json(
        client, index['list'],
    )
    assert response.status == 200
    assert listing['processes'][0].pop('state') == 'downloading'
    assert listing == {
        'processes': [
            process2,
        ],
    }

    # Attach console (to stream logs).
    stream = yield from client.ws_connect(
        process['attach']
    )
    event_log.info.assert_has_calls([mock.call(
        'process.attach',
        slug='foo.web.0',
    )])

    # Detach console.
    yield from stream.close()

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}
    event_log.info.assert_has_calls([mock.call(
        'process.delete',
        slug='foo.web.0',
    )])


@pytest.mark.asyncio
def test_create_duplicate(event_loop, server, client, file_server):

    # Create an application.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'web: python dots.py')
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'foo',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201

    # Try to create the same process again.
    response = yield from client.post(
        index['create'], data=json.dumps({
            'app': 'foo',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        }),
    )
    with autoclose(response):
        assert response.status == 409

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {},
    )
    assert response.status == 200


@pytest.mark.asyncio
def test_create_missing_fields(event_loop, server, client, file_server):

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    with autoclose(response):
        assert response.status == 200

    def without(d, key):
        return {k: v for k, v in d.items() if k != key}

    # Full request that works.
    req = {
        'app': 'foo',
        'node': 'web.0',
        'source_url': file_server.url('stuff.zip'),
        'process_type': 'web',
    }

    # App field is required.
    response = yield from client.post(
        index['create'], data=json.dumps(without(req, 'app')),
    )
    with autoclose(response):
        assert response.status == 400


@pytest.mark.asyncio
def test_unknown_slug(event_loop, server, client):

    # Try to query an unknown process.
    response = yield from client.get(
        urllib.parse.urljoin(server, '/process-status/unknown'),
        data=json.dumps({}),
    )
    with autoclose(response):
        assert response.status == 404

    # Try to delete an unknown process.
    response = yield from client.post(
        urllib.parse.urljoin(server, '/delete-process/unknown'),
        data=json.dumps({}),
    )
    with autoclose(response):
        assert response.status == 404

    # Try to attach to an unknown process.
    with pytest.raises(aiohttp.errors.WSServerHandshakeError):
        stream = yield from client.ws_connect(
            urllib.parse.urljoin(server, '/attach-console/unknown'),
        )
        print(stream)


@pytest.mark.asyncio
def test_download_failure(event_loop, server, client, file_server):
    """Follows links in REST API."""

    # NOTE: intentionally do NOT provide an archive.

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200
    assert index['create']

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'qux',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'qux'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process['state'] == 'pending'

    # Wait until download completes.
    while process['state'] in ('pending', 'downloading'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'qux'

    # Process should not have started.
    assert process['state'] == 'download failure'

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}


@pytest.mark.asyncio
def test_no_procfile(event_loop, server, client, file_server):
    """Follows links in REST API."""

    # Create an application without a Procfile.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200
    assert index['create']

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'bar',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'bar'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process['state'] == 'pending'

    # Wait until download completes.
    while process['state'] in ('pending', 'downloading', 'processing'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'bar'

    # Process should not have started.
    assert process['state'] == 'no procfile'

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}


@pytest.mark.asyncio
def test_unknown_process_type(event_loop, server, client, file_server):
    """Follows links in REST API."""

    # Create an application.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'web: python dots.py')
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200
    assert index['create']

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'meh',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'invalid',  # note: intentional.
        },
    )
    assert response.status == 201
    assert process['app'] == 'meh'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process['state'] == 'pending'

    # Wait until download completes.
    while process['state'] in ('pending', 'downloading', 'processing'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'meh'

    # Process should not have started.
    assert process['state'] == 'unknown process type'

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}


@pytest.mark.asyncio
def test_venv_failure(event_loop, server, client, file_server,
                      subprocess_factory):
    """Demonstrates resilience to internal failure."""

    # Create an application.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'web: python dots.py')
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200
    assert index['create']

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'meh',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'meh'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process['state'] == 'pending'

    # Wait until download completes.
    while process['state'] in ('pending', 'downloading'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'meh'

    # Wait until the virtual env process is spawned.
    while len(subprocess_factory.instances) == 0:
        yield from asyncio.sleep(0.1)

    # Simulate failure to spawn virtual environment.
    child = subprocess_factory.last_instance
    child.mock_complete(1)

    # Process should not have started.
    while process['state'] in ('processing'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'meh'
    assert process['state'] == 'virtual environment failure'

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}


@pytest.mark.asyncio
def test_pip_failure(event_loop, server, client, file_server,
                     subprocess_factory):
    """Demonstrates resilience to internal failure."""

    # Create an application.
    archive_path = file_server.provide('stuff.zip')
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('Procfile', 'web: python dots.py')
        archive.writestr('requirements.txt', 'Flask==0.10.1')

    # Start a new session.
    response, index = yield from get_json(
        client, server,
    )
    assert response.status == 200
    assert index['create']

    # Create a new process.
    response, process = yield from post_json(
        client, index['create'], {
            'app': 'meh',
            'node': 'web.0',
            'source_url': file_server.url('stuff.zip'),
            'process_type': 'web',
        },
    )
    assert response.status == 201
    assert process['app'] == 'meh'
    assert process['slug']
    assert process['details'] == response.headers['Location']
    assert process['state'] == 'pending'

    # Wait until download completes.
    while process['state'] in ('pending', 'downloading'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'meh'

    # Wait until the virtual env process is spawned.
    while len(subprocess_factory.instances) == 0:
        yield from asyncio.sleep(0.1)

    # Let the virtual environment appear to succeed.
    child = subprocess_factory.last_instance
    child.mock_complete(0)

    # Wait until the pip process is spawned.
    while len(subprocess_factory.instances) == 1:
        yield from asyncio.sleep(0.1)

    # Simulate failure to install dependencies.
    child = subprocess_factory.last_instance
    child.mock_complete(1)

    # Process should not have started.
    while process['state'] in ('processing'):
        yield from asyncio.sleep(0.1)
        response, process = yield from get_json(
            client,
            process['details'],
        )
        assert response.status == 200
        assert process['app'] == 'meh'
    assert process['state'] == 'pip install failure'

    # Now, delete the process.
    response, delete = yield from post_json(
        client, process['delete'], {
        },
    )
    assert response.status == 200
    assert delete == {}
