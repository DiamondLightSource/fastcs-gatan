import subprocess
import sys

from fastcs_gatan import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "fastcs_gatan", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
