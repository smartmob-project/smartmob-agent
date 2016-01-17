smartmob-agent - remote process runner
======================================

.. image:: https://img.shields.io/pypi/pyversions/smartmob-agent.svg
   :target: https://pypi.python.org/pypi/smartmob-agent
   :alt: Supported Python versions

.. image:: https://badge.fury.io/py/smartmob-agent.svg
   :target: https://pypi.python.org/pypi/smartmob-agent
   :alt: Latest PyPI version

.. image:: https://readthedocs.org/projects/smartmob-agent/badge/?version=latest
   :target: http://smartmob-agent.readthedocs.org/en/latest/?badge=latest
   :alt: Documentation Status

.. image:: https://img.shields.io/pypi/l/smartmob-agent.svg
   :alt: Released under MIT license

.. image:: https://img.shields.io/travis/smartmob-project/smartmob-agent.svg
   :target: https://travis-ci.org/smartmob-project/smartmob-agent
   :alt: Current build status

.. image:: https://coveralls.io/repos/smartmob-project/smartmob-agent/badge.svg?branch=master&service=github
   :target: https://coveralls.io/github/smartmob-project/smartmob-agent?branch=master
   :alt: Current code coverage


Description
-----------

This project is a network agent designed to remotely run applications that
follow the `The Twelve-Factor App`_.  All that is required of applications is
that they can be uploaded to the agent over the network and that they contain a
Procfile_ which can be used to start the application's processes.

.. _`The Twelve-Factor App`: http://12factor.net/
.. _Procfile: http://smartmob-rfc.readthedocs.org/en/latest/1-procfile.html


Documentation
-------------

You can find the documentation on ReadTheDocs:

- latest_

.. _latest: http://smartmob-agent.readthedocs.org/en/latest/


Contributing
------------

We welcome pull requests!  Please open up an issue on the `issue tracker`_ to
discuss, fork the project and then send in a pull request :-)

Feel free to add yourself to the ``CONTRIBUTORS`` file on your first pull
request!

.. _`issue tracker`: https://github.com/smartmob/smartmob-agent/issues


License
-------

The source code and documentation is made available under an MIT license.  See
``LICENSE`` file for details.
