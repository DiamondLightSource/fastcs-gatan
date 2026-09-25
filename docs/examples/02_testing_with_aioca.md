# Example 2: Testing fastcs-gatan over EPICS with aioca

[`aioca`](https://github.com/DiamondLightSource/aioca) is a Python (asyncio) EPICS
Channel Access client: `caget`, `caput` and `camonitor` as Python functions. It is
installed in the development environment, so it can drive fastcs-gatan's PVs where
the EPICS command-line tools are not available. PV names are explained in
[Example 1](01_dose_fractionation.md).

## Setup

Start the mock server and the driver with `- epicsca: {}` in the `transport:` list of
`gatan.yaml`, then point the client at the local IOC:

```bash
export EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO
```

## Interactive

`python -m asyncio` gives a Python prompt where `await` works directly:

```python
>>> from aioca import caget, caput, camonitor, DBR_CHAR_STR, FORMAT_CTRL, FORMAT_TIME
>>> P = "GATAN:Acquisition:"
>>> await caget("GATAN:DmVersion")
50302
```

## The main calls

```python
# Numbers: write the setting PV, read back the _RBV PV
await caput(P + "DoseFracNumFrames", 20, wait=True)   # wait=True: wait until processed
await caget(P + "DoseFracNumFrames_RBV")               # 20

# Text PVs are character arrays: use DBR_CHAR_STR both ways (like caput -S)
await caput(P + "SaveDir", "/tmp/frames", datatype=DBR_CHAR_STR, wait=True)
await caget(P + "SavedPath", datatype=DBR_CHAR_STR)

# Choice PVs: the value is an index; FORMAT_CTRL adds the option names
st = await caget(P + "DoseFracState", format=FORMAT_CTRL)
st.enums[int(st)]                                      # 'DONE'

# Alarm status and timestamp: FORMAT_TIME
cmd = await caget(P + "AcquireDoseFractionated", format=FORMAT_TIME)
cmd.severity, cmd.timestamp                            # 2 = MAJOR alarm (last command failed)

# Several PVs at once: pass a list, get a list back
await caget([P + "FramesSaved", P + "SaveError"])

# Commands: write 1 to the command PV
await caput(P + "AcquireDoseFractionated", 1, wait=True)

# Watch changes: the callback runs on every update; close when finished
m = camonitor(P + "DoseFracState", lambda v: print(v.enums[int(v)]), format=FORMAT_CTRL)
m.close()
```

A command PV is never reset to 0 after a write, but every write of 1 runs the command
again. Watch the status PVs (`DoseFracBusy`, `DoseFracState`), not the command PV.

## A pytest system test

This test starts the mock server and the driver as subprocesses and talks to them
only through PVs. It checks the status PVs, runs a full dose-fractionated exposure
(watched with `camonitor`), and checks that a failing command puts the command PV
into MAJOR alarm. Save it as e.g. `tests/system/test_ca_system.py`.

```python
"""System test: fastcs-gatan over EPICS CA, against the mock GatanSocket server."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
from aioca import (
    DBR_CHAR_STR,
    FORMAT_CTRL,
    FORMAT_TIME,
    caget,
    camonitor,
    caput,
    purge_channel_caches,
)

MOCK_DIR = "/workspaces/GatanDetectorClient-0.1.0"
P = "GATAN:Acquisition:"

CONFIG = """\
controllers:
  - id: GATAN
    type: fastcs_gatan.GatanController
    ip: 127.0.0.1
    port: {port}
transport:
  - epicsca: {{}}
"""


@pytest.fixture(scope="module")
def ioc(tmp_path_factory):
    """Start the mock server and the driver (as an EPICS IOC) in subprocesses."""
    os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
    port = 48891  # not 48890, so it doesn't clash with a mock you started by hand
    config = tmp_path_factory.mktemp("cfg") / "gatan.yaml"
    config.write_text(CONFIG.format(port=port))

    mock = subprocess.Popen(
        [sys.executable, "-m", "gatan_client.mock_server", "--k3", "--port", str(port)],
        cwd=MOCK_DIR,
    )
    time.sleep(1)
    driver = subprocess.Popen(
        [sys.executable, "-m", "fastcs_gatan", "run", str(config)],
        stdin=subprocess.PIPE,  # keeps the IPython shell waiting instead of exiting
    )
    try:
        yield
    finally:
        driver.kill()
        mock.kill()
        assert driver.stdin is not None
        driver.stdin.close()
        driver.wait()
        mock.wait()


@pytest_asyncio.fixture(autouse=True)
async def close_ca_channels():
    """aioca caches channels per event loop, and each test gets its own loop.
    Drop them while this test's loop is still running, or they fire callbacks
    into a closed loop when the IOC stops."""
    yield
    purge_channel_caches()


async def wait_for_ioc(timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            await caget("GATAN:DmVersion", timeout=1)
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_status_pvs(ioc):
    await wait_for_ioc()
    assert await caget("GATAN:DmVersion") == 50302  # the mock's DM version
    assert await caget("GATAN:Camera:NumCameras") > 0


@pytest.mark.asyncio
async def test_dose_fractionated_exposure(ioc, tmp_path: Path):
    await wait_for_ioc()
    await caput(P + "ReadMode", 3, wait=True)  # K3 linear: mock allows small frames
    await caput(P + "Width", 512, wait=True)
    await caput(P + "Height", 512, wait=True)
    await caput(P + "SaveDir", str(tmp_path), datatype=DBR_CHAR_STR, wait=True)
    await caput(P + "SaveRootName", "movie", datatype=DBR_CHAR_STR, wait=True)
    await caput(P + "DoseFracNumFrames", 10, wait=True)
    await caput(P + "DoseFracExposure", 0.5, wait=True)
    assert await caget(P + "DoseFracNumFrames_RBV") == 10

    # Watch the state PV, then start the exposure and wait until it reports DONE.
    states: list[str] = []
    done = asyncio.Event()

    def on_state(value):
        name = value.enums[int(value)]
        states.append(name)
        if name in ("DONE", "FAILED"):
            done.set()

    monitor = camonitor(P + "DoseFracState", on_state, format=FORMAT_CTRL)
    try:
        await caput(P + "AcquireDoseFractionated", 1, wait=True)
        await asyncio.wait_for(done.wait(), timeout=10)
    finally:
        monitor.close()

    message = await caget(P + "DoseFracMessage", datatype=DBR_CHAR_STR)
    assert states[-1] == "DONE", message
    assert await caget(P + "DoseFracBusy") == 0
    assert await caget(P + "FramesSaved") == 10
    assert await caget(P + "SaveError") == 0
    saved = await caget(P + "SavedPath", datatype=DBR_CHAR_STR)
    assert saved.endswith("movie.mrc")


@pytest.mark.asyncio
async def test_failing_command_raises_alarm(ioc):
    await wait_for_ioc()
    await caput(P + "SaveDir", "", datatype=DBR_CHAR_STR, wait=True)  # invalid
    await caput(P + "AcquireDoseFractionated", 1, wait=True)
    cmd = await caget(P + "AcquireDoseFractionated", format=FORMAT_TIME)
    assert cmd.severity == 2  # MAJOR alarm: the command raised
```

Things to know, all caught by the repo's `filterwarnings = "error"` pytest setting:

- **Drop aioca's connections after each test.** aioca caches connections per event
  loop, and pytest-asyncio gives each test its own loop; when the IOC stops, cached
  connections fire callbacks into closed loops ("Event loop is closed").
  `purge_channel_caches()` in an async fixture fixes this.
- **Close the driver's stdin pipe** after the process stops, or pytest reports a
  `ResourceWarning`.
- **Start the driver with `stdin=PIPE`.** Otherwise its IPython shell exits at once and
  takes the IOC with it.
- **Use a different mock port** (48891 here), so the test does not clash with a mock
  server started by hand on 48890.
