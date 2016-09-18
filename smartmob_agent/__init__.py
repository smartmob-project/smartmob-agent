# -*- coding: utf-8 -*-

import argparse
import asyncio
import contextlib
import fluent.sender
import json
import os
import os.path
import pkg_resources
import procfile
import structlog
import structlog.processors
import sys
import tarfile
import timeit
import uuid
import zipfile

from aiohttp import ClientSession, web
from datetime import datetime, timezone
from strawboss import run_and_respawn
from urllib.parse import urlsplit
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
cli.add_argument('--log-format', action='store', dest='log_format',
                 type=str, choices={'kv', 'json'}, default='kv')
cli.add_argument('--utc', action='store_true', dest='utc_timestamps',
                 default=False)
cli.add_argument('--logging-endpoint', action='store', dest='logging_endpoint',
                 default=None)


class TimeStamper(object):
    """Custom implementation of ``structlog.processors.TimeStamper``.

    See:
    - https://github.com/hynek/structlog/issues/81
    """

    def __init__(self, key, utc):
        self._key = key
        self._utc = utc
        if utc:
            def now():
                return datetime.utcnow().replace(tzinfo=timezone.utc)
        else:
            def now():
                return datetime.now()
        self._now = now

    def __call__(self, _, __, event_dict):
        timestamp = event_dict.get('@timestamp')
        if timestamp is None:
            timestamp = self._now()
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        event_dict['@timestamp'] = timestamp
        return event_dict


async def inject_request_id(app, handler):
    """aiohttp middleware: ensures each request has a unique request ID.

    See: ``inject_request_id``.
    """

    async def trace_request(request):
        request['x-request-id'] = \
            request.headers.get('x-request-id') or str(uuid.uuid4())
        return await handler(request)

    return trace_request


async def echo_request_id(request, response):
    """aiohttp signal: ensures each response contains the request ID.

    See: ``echo_request_id``.
    """
    response.headers['X-Request-Id'] = request.get('x-request-id', '?')


async def access_log_middleware(app, handler):
    """Log each request in structured event log."""

    event_log = app.get('smartmob.event_log') or structlog.get_logger()
    clock = app.get('smartmob.clock') or timeit.default_timer

    # Keep the request arrival time to ensure we get intuitive logging of
    # events.
    arrival_time = datetime.utcnow().replace(tzinfo=timezone.utc)

    async def access_log(request):
        ref = clock()
        try:
            response = await handler(request)
            event_log.info(
                'http.access',
                path=request.path,
                outcome=response.status,
                duration=(clock()-ref),
                request=request.get('x-request-id', '?'),
                **{'@timestamp': arrival_time}
            )
            return response
        except web.HTTPException as error:
            event_log.info(
                'http.access',
                path=request.path,
                outcome=error.status,
                duration=(clock()-ref),
                request=request.get('x-request-id', '?'),
                **{'@timestamp': arrival_time}
            )
            raise
        except Exception:
            event_log.info(
                'http.access',
                path=request.path,
                outcome=500,
                duration=(clock()-ref),
                request=request.get('x-request-id', '?'),
                **{'@timestamp': arrival_time}
            )
            raise

    return access_log


class FluentLoggerFactory:
    """For use with ``structlog.configure(logger_factory=...)``."""

    @classmethod
    def from_url(cls, url):
        parts = urlsplit(url)
        if parts.scheme != 'fluent':
            raise ValueError('Invalid URL: "%s".' % url)
        if parts.query or parts.fragment:
            raise ValueError('Invalid URL: "%s".' % url)
        netloc = parts.netloc.rsplit(':', 1)
        if len(netloc) == 1:
            host, port = netloc[0], 24224
        else:
            host, port = netloc
            try:
                port = int(port)
            except ValueError:
                raise ValueError('Invalid URL: "%s".' % url)
        return FluentLoggerFactory(parts.path[1:], host, port)

    def __init__(self, app, host, port):
        self._app = app
        self._host = host
        self._port = port
        self._sender = fluent.sender.FluentSender(app, host=host, port=port)

    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    @property
    def app(self):
        return self._app

    def __call__(self):
        return FluentLogger(self._sender)


class FluentLogger:
    """Structlog logger that sends events to FluentD."""

    def __init__(self, sender):
        self._sender = sender

    def info(self, event, **kwds):
        self._sender.emit(event, kwds)


def configure_logging(log_format, utc, endpoint):
    processors = [
        TimeStamper(
            key='@timestamp',
            utc=utc,
        ),
    ]
    if endpoint.startswith('file://'):
        path = endpoint[7:]
        if path == '/dev/stdout':
            stream = sys.stdout
        elif path == '/dev/stderr':
            stream = sys.stderr
        else:
            stream = open(path, 'w')
        logger_factory = structlog.PrintLoggerFactory(file=stream)
        if log_format == 'kv':
            processors.append(structlog.processors.KeyValueRenderer(
                sort_keys=True,
                key_order=['@timestamp', 'event'],
            ))
        else:
            processors.append(structlog.processors.JSONRenderer(
                sort_keys=True,
            ))
    elif endpoint.startswith('fluent://'):
        utc = True
        logger_factory = FluentLoggerFactory.from_url(endpoint)
    else:
        raise ValueError('Invalid logging endpoint "%s".' % endpoint)
    structlog.configure(
        processors=processors,
        logger_factory=logger_factory,
    )


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
        reject = lambda _1, _2: False  # noqa: E731

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
    event_log = request.app.get('smartmob.event_log') or structlog.get_logger()

    # Validate request.
    r = yield from request.json()
    try:
        r = CreateRequest(r)
    except MultipleInvalid:
        raise web.HTTPBadRequest

    # Initiate process creation.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = '.'.join((r['app'], r['node']))
    if slug in processes:
        raise web.HTTPConflict

    # Log the request.
    event_log.info('process.create', app=r['app'], node=r['node'], slug=slug)

    # Proceed.
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

    event_log = request.app.get('smartmob.event_log') or structlog.get_logger()

    # Resolve the process.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = request.match_info['slug']
    try:
        process = processes[slug]
    except KeyError:
        raise web.HTTPNotFound

    # Log the request.
    event_log.info('process.delete', slug=slug)

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

    event_log = request.app.get('smartmob.event_log') or structlog.get_logger()

    # Must connect here with a WebSocket.
    if request.headers.get('Upgrade', '').lower() != 'websocket':
        pass

    # Resolve the process.
    processes = request.app.setdefault('smartmob.processes', {})
    slug = request.match_info['slug']
    if slug not in processes:
        raise web.HTTPNotFound

    # WebSocket handshake.
    stream = web.WebSocketResponse()
    yield from stream.prepare(request)

    # TODO: retrieve data from the process and pipe it to the WebSocket.
    #       Strawboss implementation doesn't provide anything for this at the
    #       moment, so we'll have to do this later.

    # Log the request.
    event_log.info('process.attach', slug=slug)

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
def start_responder(host='127.0.0.1', port=8080, event_log=None, loop=None):
    """."""

    loop = loop or asyncio.get_event_loop()
    event_log = event_log or structlog.get_logger()

    # Prepare a web application.
    app = web.Application(loop=loop, middlewares=[
        inject_request_id,
        access_log_middleware,
    ])
    app.on_response_prepare.append(echo_request_id)
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

    event_log.info('bind', transport='tcp', host=host, port=port)

    # Start accepting connections.
    handler = app.make_handler()
    server = yield from loop.create_server(handler, host, port)
    return app, handler, server


@contextlib.contextmanager
def responder(event_loop, event_log=None, host='127.0.0.1', port=8080):
    event_log = event_log or structlog.get_logger()
    app, handler, server = event_loop.run_until_complete(
        start_responder(loop=event_loop, event_log=event_log,
                        host=host, port=port)
    )
    client = ClientSession(loop=event_loop)
    with autoclose(client):
        app['smartmob.http-client'] = client
        app['smartmob.event_log'] = event_log
        app['smartmob.clock'] = timeit.default_timer
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

    # Dynamic defaults.
    logging_endpoint = arguments.logging_endpoint
    if not logging_endpoint:
        logging_endpoint = os.environ.get('SMARTMOB_LOGGING_ENDPOINT')
    if not logging_endpoint:
        logging_endpoint = 'file:///dev/stdout'

    # Initialize logger.
    configure_logging(
        log_format=arguments.log_format,
        utc=arguments.utc_timestamps,
        endpoint=logging_endpoint,
    )
    event_log = structlog.get_logger()

    # Start the event loop.
    loop = asyncio.get_event_loop()

    # Run the agent :-)
    try:
        with responder(loop, event_log=event_log,
                       host=arguments.host,
                       port=arguments.port):
            loop.run_forever()  # pragma: no cover
    except KeyboardInterrupt:
        event_log.info('stop', reason='ctrl-c')


if __name__ == '__main__':  # pragma: no cover
    # Proceed as requested :-)
    sys.exit(main(sys.argv[1:]))
