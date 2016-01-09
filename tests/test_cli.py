# -*- coding: utf-8 -*-

import pytest

from smartmob_agent import cli, version

def test_version(capsys):
    with pytest.raises(SystemExit) as error:
        cli.parse_args(['--version'])
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version
