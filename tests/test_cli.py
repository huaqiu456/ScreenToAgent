from __future__ import annotations

import pytest

from screen_to_agent import __version__
from screen_to_agent.app import main


def test_version_is_declared() -> None:
    assert __version__ == "0.10.0"


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "screen-to-agent" in capsys.readouterr().out
