smartmob-agent -- remote process runner
=======================================

Description
===========

This project is a network agent designed to remotely run applications that
follow the `The Twelve-Factor App`_.  All that is required of applications is
that they can be uploaded to the agent over the network and that they contain a
Procfile_ which can be used to start the application's processes.

.. _`The Twelve-Factor App`: http://12factor.net/
.. _Procfile: http://smartmob-rfc.readthedocs.org/en/latest/1-procfile.html


Command-line interface
======================

Run an HTTP service with a REST API to allows clients to remotely start
programs as children of this program.

To stop, press CTRL-C or send SIGINT and wait for all children to end.  Killing
this program using SIGKILL will automatically terminate all children.

Logs from children are silently discarded by default.  Clients can connect
a WebSocket_ to stream output to a destination of their choice.

When a child process ends, it is automatically restarted until the client
explicitly requests the termination of the child process.

Errors and warnings are sent to stderr.  You can filter these or send them to a
different file if you wish.

.. program:: smartmob-agent

.. option:: --version

   Print version and exit.

.. option:: --help

   Print usage and exit.


REST API
========

Walk through
------------

.. testsetup::

   import asyncio

   from smartmob_agent import (
       start_responder,
   )

   loop = asyncio.get_event_loop()
   app, handler, server = loop.run_until_complete(start_responder(
       host='127.0.0.1', port=8080, loop=loop,
   ))

   import aiohttp
   import json

   client = aiohttp.ClientSession()

   APP_ROOT = 'http://127.0.0.1:8080'

Starting a new session
~~~~~~~~~~~~~~~~~~~~~~

First, query the application root URL to get the links to the actions that are
available to you (see `Index`_ in the API reference).

.. doctest::

   >>> response = loop.run_until_complete(client.get('http://127.0.0.1:8080'))
   >>> assert response.status == 200
   >>> index = loop.run_until_complete(response.read())
   >>> index = json.loads(index.decode('utf-8'))
   >>> print(json.dumps(index, indent=4, sort_keys=True))
   {
       "create": "http://127.0.0.1:8080/create-process",
       "list": "http://127.0.0.1:8080/list-processes"
   }

Then, you can do things like query the current listing (see `Listing`_ in the
API reference).

.. doctest::

   >>> response = loop.run_until_complete(client.get(index['list']))
   >>> assert response.status == 200
   >>> listing = loop.run_until_complete(response.read())
   >>> listing = json.loads(listing.decode('utf-8'))
   >>> print(json.dumps(listing, indent=4, sort_keys=True))
   {
       "processes": []
   }

Creating a process
~~~~~~~~~~~~~~~~~~

Next, you can start a process (see `Create request`_ in the API reference).

.. doctest::

   >>> response = loop.run_until_complete(client.post(
   ...     index['create'],
   ...     data=json.dumps({
   ...         'app': "myapp",
   ...         'source_url': "http://...",
   ...         'process_type': "web",
   ...         'node': "web.0",
   ...     }),
   ... ))
   >>> assert response.status == 201
   >>> process = loop.run_until_complete(response.read())
   >>> process = json.loads(process.decode('utf-8'))
   >>> print(json.dumps(process, indent=4, sort_keys=True))
   {
       "app": "myapp",
       "attach": "ws://127.0.0.1:8080/attach-console/myapp.web.0",
       "delete": "http://127.0.0.1:8080/delete-process/myapp.web.0",
       "details": "http://127.0.0.1:8080/process-status/myapp.web.0",
       "slug": "myapp.web.0",
       "state": "pending"
   }

Once the process is created, it should appear in the listing (see `Listing`_ in
the API reference).

.. doctest::

   >>> response = loop.run_until_complete(client.get(index['list']))
   >>> assert response.status == 200
   >>> listing = loop.run_until_complete(response.read())
   >>> listing = json.loads(listing.decode('utf-8'))
   >>> print(json.dumps(listing, indent=4, sort_keys=True))
   {
       "processes": [
           {
               "app": "myapp",
               "attach": "ws://127.0.0.1:8080/attach-console/myapp.web.0",
               "delete": "http://127.0.0.1:8080/delete-process/myapp.web.0",
               "details": "http://127.0.0.1:8080/process-status/myapp.web.0",
               "slug": "myapp.web.0",
               "state": "pending"
           }
       ]
   }

Streaming logs
~~~~~~~~~~~~~~

If you wish to, you can connect a WebSocket_ to stream output from the process
to your local machine.

.. _WebSocket: https://en.wikipedia.org/wiki/WebSocket

.. doctest::

   >>> stream = loop.run_until_complete(client.ws_connect(
   ...     process['attach']
   ... ))
   >>> # ...
   >>> assert loop.run_until_complete(stream.close())

Deleting a process
~~~~~~~~~~~~~~~~~~

When you're done, you can delete this process (see `Delete request`_ in the API
reference).

.. doctest::

   >>> response = loop.run_until_complete(client.post(
   ...     process['delete'],
   ...     data=json.dumps({}),
   ... ))
   >>> assert response.status == 200

.. testcleanup::

   client.close()
   server.close()
   loop.run_until_complete(server.wait_closed())
   loop.run_until_complete(handler.finish_connections(1.0))
   loop.run_until_complete(app.finish())


Reference
---------

Index
~~~~~

Content type: ``application/json``.

+--------+------+-------------------------------------------------------------+
| Field  | Type | Value                                                       |
+========+======+=============================================================+
| list   | URL  | HTTP GET to obtain a `Listing`_ document.                   |
+--------+------+-------------------------------------------------------------+
| create | URL  | HTTP POST `Create request`_ documents here.  The response   |
|        |      | will return a `Process status`_ document.                   |
+--------+------+-------------------------------------------------------------+

Listing
~~~~~~~

Content type: ``application/json``.

+-----------+------+----------------------------------------+
| Field     | Type | Value                                  |
+===========+======+========================================+
| processes | list | A list of `Process status`_ documents. |
+-----------+------+----------------------------------------+

Process status
~~~~~~~~~~~~~~

Content type: ``application/json``.

+--------+--------+-----------------------------------------------------------+
| Field  | Type   | Value                                                     |
+========+========+===========================================================+
| app    | string | Value passed in the `Create request`_ document.           |
+--------+--------+-----------------------------------------------------------+
| node   | string | Value passed in the `Create request`_ document.           |
+--------+--------+-----------------------------------------------------------+
| slug   | string | Unique identifier for the process.                        |
+--------+--------+-----------------------------------------------------------+
| attach | URL    | Connect a WebSocket to receive output from the process.   |
|        |        | Each line of output is in a text frame.                   |
+--------+--------+-----------------------------------------------------------+
| status | URL    | HTTP GET to obtain an updated `Process status`_ document. |
+--------+--------+-----------------------------------------------------------+
| delete | URL    | HTTP POST a `Delete request`_ to delete the process.      |
+--------+--------+-----------------------------------------------------------+

Create request
~~~~~~~~~~~~~~

Content type: ``application/json``.

+--------------+--------+-----------------------------------------------------+
| Field        | Type   | Value                                               |
+==============+========+=====================================================+
| app          | string | Name of the application.  Need not be unique among  |
|              |        | processes.                                          |
+--------------+--------+-----------------------------------------------------+
| node         | string | Name of the process.  By convention, this should be |
|              |        | the ``process_type``, followed by a period,         |
|              |        | followed by a number.                               |
+--------------+--------+-----------------------------------------------------+
| process_type | string | Type of process to launch.  This is used as a key   |
|              |        | into the map contained in the Procfile_ that is at  |
|              |        | the root of the application's source archive.       |
+--------------+--------+-----------------------------------------------------+
| source_url   | URL    | During initialization, the agent will issue an HTTP |
|              |        | GET request to this URL to download the source      |
|              |        | archive which contains the Procfile_ and other      |
|              |        | files containing application code and data.         |
+--------------+--------+-----------------------------------------------------+
| env          | object | String to string mapping of environment variables   |
|              |        | that should be injected into the child process when |
|              |        | spawning it (in addition to those specified for the |
|              |        | associated command found in the Procfile_).         |
+--------------+--------+-----------------------------------------------------+

Delete request
~~~~~~~~~~~~~~

Content type: ``application/json``.

For the moment, this document is always empty.


Indexes and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
