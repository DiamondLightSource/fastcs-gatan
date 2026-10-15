import subprocess
import sys

from fastcs_gatan import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "fastcs_gatan", "--version"]
    output = subprocess.check_output(cmd).decode().splitlines()
    assert output[0] == f"GatanController: {__version__}"
