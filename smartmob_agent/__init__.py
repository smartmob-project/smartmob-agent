# -*- coding: utf-8 -*-

import argparse
import asyncio
import contextlib
import json
import os
import os.path
import pkg_resources
import procfile
import sys
import tarfile
import venv
import zipfile

from aiohttp import ClientSession, web
from strawboss import run_and_respawn
from voluptuous import Schema, Required, MultipleInvalid

version = pkg_resources.resource_string('smartmob_agent', 'version.txt')
version = version.decode('utf-8').strip()
"""Package version (as a dotted string)."""

cli = argparse.ArgumentParser(description="Run programs.")
cli.add_argument('--version', action='version', version=version,
                 help="Print version and exit.")
cli.add_argument('--host', action='store', dest='host',
                 type=str, default='0.0.0.0')
cli.add_argument('--port', action='store', dest='port',
                 type=int, default=8080)

Index = Schema({
    Required('list'): str,  # GET to query listing.
    Required('create'): str,  # POST to create new process.
})

ProcessDetails = Schema({
    Required('app'): str,  # redundant.
    # NODE
    Required('slug'): str,  # persistent process ID (not actial PID).
    Required('attach'): str,  # WebSocket here to stream logs.
    Required('details'): str,  # GET to query status.
    Required('delete'): str,  # POST here to delete.
    Required('state'): str,  # enum.
})

Listing = Schema({
    'processes': [ProcessDetails],
})

# TODO: configure text/binary output?
CreateRequest = Schema({
    Required('app'): str,
    Required('node'): str,
    Required('source_url'): str,
    Required('process_type'): str,
    'env': {str: str},
})

@asyncio.coroutine
def index(request):
    list_url = '%s://%s%s' % (
        request.scheme,
        request.host,
        request.app.router['list-processes'].url(),
    )
    create_url = '%s://%s%s' % (
        request.scheme,
        request.host,
        request.app.router['create-process'].url(),
    )
    r = Index({
        'list': list_url,
        'create': create_url,
    })
    return web.Response(
        content_type='application/json',
        body=json.dumps(r).encode('utf-8'),
    )

def make_details(request, process):
    slug = process['slug']
    details_url = '%s://%s%s' % (
        request.scheme,
        request.host,
        request.app.router['process-status'].url(parts={'slug': slug}),
    )
    attach_url = '%s://%s%s' % (
        'ws',
        request.host,
        request.app.router['attach-console'].url(parts={'slug': slug}),
    )
    delete_url = '%s://%s%s' % (
        request.scheme,
        request.host,
        request.app.router['delete-process'].url(parts={'slug': slug}),
    )
    return {
        'app': process['app'],
        'slug': process['slug'],
        'attach': attach_url,
        'details': details_url,
        'delete': delete_url,
        'state': process['state'],
    }


def unpack_archive(archive_format, archive_path, source_path):
    """Extract a .zip/.tar.gz archive to a folder."""
    if archive_format not in ('zip', 'tar'):
        raise ValueError('Unknown archive format "%s".' % archive_format)
    if archive_format == 'zip':
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(source_path)
    if archive_format == 'tar':
        with tarfile.open(archive_path) as archive:
            archive.extractall(source_path)


@contextlib.contextmanager
def autoclose(x):
    try:
        yield
    finally:
        x.close()


# TODO: stream by chunk to handle large archives.
@asyncio.coroutine
def download(client, url, path, reject=None):
    if reject is None:
        reject = lambda _1, _2: False

    response = yield from client.get(url)
    with autoclose(response):
        if response.status != 200:
            raise Exception('Download failed.')
        if reject(url, response):
            raise Exception('Download rejected.')
        with open(path, 'wb') as archive:
            content = yield from response.read()
            archive.write(content)

    return response.headers['Content-Type']


@asyncio.coroutine
def create_venv(path):
    command = [
        sys.executable, '-m', 'virtualenv', path,
    ]
    child = yield from asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = yield from child.communicate()
    status = yield from child.wait()
    if status != 0:
        raise Exception('command failed')


@asyncio.coroutine
def pip_install(venv_path, deps_path):
    command = [
        os.path.join(venv_path, 'bin', 'pip'),
        'install', '-r', deps_path,
    ]
    child = yield from asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = yield from child.communicate()
    status = yield from child.wait()
    if status != 0:
        raise Exception('command failed')


def negate(f):
    def _(*args, **kwds):
        return not f(*args, **kwds)
    return _


@asyncio.coroutine
def start_process(app, process, loop=None):

    loop = loop or asyncio.get_event_loop()

    # Download source archive.
    def is_archive(url, response):
        return response.headers['Content-Type'] in (
            'application/zip',
            'application/x-gtar',
        )

    client = app['smartmob.http-client']
    archive_path = os.path.join(
        '.', '.smartmob', 'archives',
        process['slug'],
    )
    process['state'] = 'downloading'
    try:
        content_type = yield from download(
            client, process['source_url'],
            archive_path,
            reject=negate(is_archive),
        )
    except:
        process['state'] = 'download failure'
        raise
    process['state'] = 'unpacking'

    # Deduce archive format.
    archive_format = {
        'application/zip': 'zip',
        'application/x-gtar': 'tar',
    }[content_type]

    # Unpack source archive.
    source_path = os.path.join(
        '.', '.smartmob', 'sources', process['slug'],
    )
    yield from loop.run_in_executor(
        None, unpack_archive, archive_format, archive_path, source_path,
    )
    process['state'] = 'processing'

    # Load Procfile and lookup process type.
    try:
        process_types = procfile.loadfile(
            os.path.join(source_path, 'Procfile'),
        )
    except FileNotFoundError:
        process['state'] = 'no procfile'
        return
    try:
        process_type = process_types[process['process_type']]
    except KeyError:
        process['state'] = 'unknown process type'
        return

    # Create virtual environment.
    venv_path = os.path.join(
        '.', '.smartmob', 'envs', process['slug'],
    )
    try:
        yield from create_venv(venv_path)
    except:
        process['state'] = 'virtual environment failure'
        raise

    # Install dependencies.
    deps_path = os.path.join(source_path, 'requirements.txt')
    try:
        yield from pip_install(venv_path, deps_path)
    except:
        process['state'] = 'pip install failure'
        raise

    # Run it again and again until somebody requests to kill this process.
    #
    # TODO: figure out how to get status updates so REST API reflects actual
    #       status.
    yield from run_and_respawn(
        name=process['slug'],
        cmd=process_type['cmd'],
        env=dict(process_type['env']),
        shutdown=process['stop'],
    )

@asyncio.coroutine
def create_process(request):
    loop = asyncio.get_event_loop()

    # Validate request.
    r = yield from request.json()
    try:
        r = CreateRequest(r)
    except MultipleInvalid:
        raise web.HTTPBadRequest
    # Initiate process creation.
    #
    # TODO: something useful.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = '.'.join((r['app'], r['node']))
    if slug in processes:
        raise web.HTTPConflict
    r['slug'] = slug
    r['stop'] = asyncio.Future()
    r['task'] = loop.create_task(
        start_process(request.app, r, loop=loop),
    )
    r['state'] = 'pending'
    processes[slug] = r
    # Format response.
    process = make_details(request, r)
    return web.HTTPCreated(
        content_type='application/json',
        body=json.dumps(ProcessDetails(
            process,
        )).encode('utf-8'),
        headers={
            'Location': process['details'],
        },
    )

@asyncio.coroutine
def process_status(request):
    # Lookup process.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = request.match_info['slug']
    try:
        process = processes[slug]
    except KeyError:
        raise web.HTTPNotFound
    # Format response.
    return web.Response(
        content_type='application/json',
        body=json.dumps(ProcessDetails(
            make_details(request, process)
        )).encode('utf-8'),
    )

@asyncio.coroutine
def delete_process(request):
    # Resolve the process.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = request.match_info['slug']
    try:
        process = processes[slug]
    except KeyError:
        raise web.HTTPNotFound
    # Kill the process and wait for it to complete.
    process['stop'].set_result(None)
    try:
        yield from process['task']
    except Exception:  # TODO: be more accurate!
        pass
    # Erase bookkeeping.
    del processes[slug]
    # Format the response.
    return web.Response(
        content_type='application/json',
        body=json.dumps({
            # ...
        }).encode('utf-8'),
    )

@asyncio.coroutine
def attach_console(request):
    # Must connect here with a WebSocket.
    if request.headers.get('Upgrade', '').lower() != 'websocket':
        pass

    # Resolve the process.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = request.match_info['slug']
    try:
        process = processes[slug]
    except KeyError:
        raise web.HTTPNotFound

    # WebSocket handshake.
    stream = web.WebSocketResponse()
    yield from stream.prepare(request)

    # TODO: retrieve data from the process and pipe it to the WebSocket.
    #       Strawboss implementation doesn't provide anything for this at the
    #       moment, so we'll have to do this later.

    # Close the WebSocket.
    yield from stream.close()

    # Required by the framework, but I don't know why.
    return stream


@asyncio.coroutine
def list_processes(request):
    processes = request.app.setdefault('smartmob.processes', {})
    return web.Response(
        content_type='application/json',
        body=json.dumps(Listing({
            'processes': [
                make_details(request, p) for p in processes.values()
            ],
        })).encode('utf-8'),
    )

@asyncio.coroutine
def start_responder(host='127.0.0.1', port=8080, loop=None):
    """."""

    loop = loop or asyncio.get_event_loop()

    # Prepare a web application.
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)
    app.router.add_route('POST', '/create-process',
                         create_process, name='create-process')
    app.router.add_route('GET', '/process-status/{slug}',
                         process_status, name='process-status')
    app.router.add_route('POST', '/delete-process/{slug}',
                         delete_process, name='delete-process')
    app.router.add_route('GET', '/attach-console/{slug}',
                         attach_console, name='attach-console')
    app.router.add_route('GET', '/list-processes',
                         list_processes, name='list-processes')

    # Create storage folders.
    archives_path = os.path.join(
        '.', '.smartmob', 'archives',
    )
    if not os.path.isdir(archives_path):
        os.makedirs(archives_path)
    sources_path = os.path.join(
        '.', '.smartmob', 'sources',
    )
    if not os.path.isdir(sources_path):
        os.makedirs(sources_path)
    envs_path = os.path.join(
        '.', '.smartmob', 'envs',
    )
    if not os.path.isdir(envs_path):
        os.makedirs(envs_path)

    # Start accepting connections.
    handler = app.make_handler()
    server = yield from loop.create_server(handler, host, port)
    return app, handler, server


@contextlib.contextmanager
def responder(event_loop, host='127.0.0.1', port=8080):
    app, handler, server = event_loop.run_until_complete(
        start_responder(loop=event_loop, host=host, port=port)
    )
    client = ClientSession(loop=event_loop)
    with autoclose(client):
        app['smartmob.http-client'] = client
        try:
            yield 'http://127.0.0.1:8080', app, handler, server
        finally:
            server.close()
            event_loop.run_until_complete(server.wait_closed())
            event_loop.run_until_complete(handler.finish_connections(1.0))
            event_loop.run_until_complete(app.finish())


def main(arguments=None):
    """Command-line entry point.

    :param arguments: List of strings that contain the command-line arguments.
       When ``None``, the command-line arguments are looked up in ``sys.argv``
       (``sys.argv[0]`` is ignored).
    :return: This function has no return value.
    :raise SystemExit: The command-line arguments are invalid.
    """

    # Parse command-line arguments.
    if arguments is None:
        arguments = sys.argv[1:]
    arguments = cli.parse_args(arguments)

    # Start the event loop.
    loop = asyncio.get_event_loop()

    # Run the agent :-)
    try:
        with responder(loop, host=arguments.host, port=arguments.port):
            loop.run_forever()  # pragma: no cover
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':  # pragma: no cover
    # Proceed as requested :-)
    sys.exit(main(sys.argv[1:]))
