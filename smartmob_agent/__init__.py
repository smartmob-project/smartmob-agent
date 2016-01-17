# -*- coding: utf-8 -*-

import argparse
import asyncio
import json
import pkg_resources
import sys

from aiohttp import web
from voluptuous import Schema, Required, MultipleInvalid

version = pkg_resources.resource_string('smartmob_agent', 'version.txt')
version = version.decode('utf-8').strip()
"""Package version (as a dotted string)."""

cli = argparse.ArgumentParser(description="Run programs.")
cli.add_argument('--version', action='version', version=version,
                 help="Print version and exit.")

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
    }

@asyncio.coroutine
def create_process(request):
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
    print('PROCESS:', process)
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
    # Erase the process.
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
    if request.headers.get('Upgrade', '').lower() != 'websocket':
        pass
    stream = web.WebSocketResponse()
    yield from stream.prepare(request)
    yield from stream.close()
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
def start_responder(endpoint=('127.0.0.1', 8080), loop=None):
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

    # Start accepting connections.
    handler = app.make_handler()
    server = yield from loop.create_server(
        handler, endpoint[0], endpoint[1]
    )
    return app, handler, server

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
    app, handler, server = loop.run_until_complete(start_responder(loop=loop))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.run_until_complete(handler.finish_connections(1.0))
        loop.run_until_complete(app.finish())

if __name__ == '__main__':  # pragma: no cover
    # Proceed as requested :-)
    sys.exit(main(sys.argv[1:]))
