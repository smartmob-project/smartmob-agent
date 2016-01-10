# -*- coding: utf-8 -*-

import argparse
import asyncio
import pkg_resources
import sys

from aiohttp import web

version = pkg_resources.resource_string('smartmob_agent', 'version.txt')
version = version.decode('utf-8').strip()
"""Package version (as a dotted string)."""

cli = argparse.ArgumentParser(description="Run programs.")
cli.add_argument('--version', action='version', version=version,
                 help="Print version and exit.")

@asyncio.coroutine
def index(request):
    # Handle websockets & HTTP on the same route.
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        stream = web.WebSocketResponse()
        yield from stream.prepare(request)
        stream.send_str('hello, world!')
        yield from stream.close()
        return stream
    else:
        text = 'hello, world!'
        return web.Response(body=text.encode('utf-8'))

@asyncio.coroutine
def start_responder(endpoint=('127.0.0.1', 8080), loop=None):
    """."""

    loop = loop or asyncio.get_event_loop()

    # Prepare a web application.
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)

    # Start accepting connections.
    server = yield from loop.create_server(
        app.make_handler(), endpoint[0], endpoint[1]
    )
    return server

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
    loop.run_until_complete(start_responder(loop=loop))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':  # pragma: no cover
    # Proceed as requested :-)
    sys.exit(main(sys.argv[1:]))
