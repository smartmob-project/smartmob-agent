# -*- coding: utf-8 -*-

import pytest

from smartmob_agent import cli, version


def test_version(capsys):
    with pytest.raises(SystemExit) as error:
        cli.parse_args(['--version'])
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version


def test_defaults(capsys):
    arguments = cli.parse_args([])
    assert arguments.host == '0.0.0.0'
    assert arguments.port == 8080


def test_host(capsys):
    arguments = cli.parse_args(['--host=127.0.0.1'])
    assert arguments.host == '127.0.0.1'


def test_port(capsys):
    arguments = cli.parse_args(['--port=80'])
    assert arguments.port == 80
