# -*- coding: utf-8 -*-

import pytest
from unittest import mock

from smartmob_agent import main, version

@mock.patch('sys.argv', ['smartmob-agent', '--version'])
def test_main_sys_argv(capsys):
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version

def test_main_explicit_args(capsys):
    with pytest.raises(SystemExit) as error:
        main(['smartmob-agent', '--version'])
    assert error.value.args[0] == 0
    stdout, _ = capsys.readouterr()
    assert stdout.strip() == version
