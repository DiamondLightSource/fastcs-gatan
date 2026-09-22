"""Controller tests: construction/wiring, and the dose-fractionation sequence
against a fake connection. Real wire-protocol behavior is exercised against a
loopback socket pair in test_gatan_socket_wire.py. ``GatanController.
initialise()`` isn't called here since it needs a live socket.
"""

import asyncio
import contextlib
import threading

import pytest
from fastcs.connections import IPConnectionSettings

from fastcs_gatan.controllers.acquisition_controller import (
    AcquisitionController,
    DoseFracState,
)
from fastcs_gatan.controllers.gatan_controller import GatanController


def test_construct_controller():
    controller = GatanController(
        connection_settings=IPConnectionSettings(ip="127.0.0.1", port=48890)
    )
    assert controller.connection.host == "127.0.0.1"
    assert controller.connection.port == 48890
    assert controller.connection.connected is False


def test_continuous_still_raises_not_implemented():
    """Continuous acquisition is still deferred — pin that it fails loudly
    rather than silently doing the wrong thing."""
    controller = GatanController(
        connection_settings=IPConnectionSettings(ip="127.0.0.1", port=48890)
    )
    with pytest.raises(NotImplementedError):
        controller.connection.stop_continuous_camera()


class _FakeConnection:
    """Records the dose-fractionation call sequence; no socket."""

    def __init__(self, setup_error: int = 0, num_saved: int = 20) -> None:
        self.calls: list[tuple] = []
        self.setup_error = setup_error
        self.num_saved = num_saved
        self.release = threading.Event()

    @contextlib.contextmanager
    def exclusive(self):
        yield

    def set_k2_parameters2(self, **kwargs):
        self.calls.append(("k2", kwargs["dose_frac"], kwargs["frame_time"]))

    def setup_file_saving2(self, **kwargs):
        self.calls.append(("setup", kwargs["save_dir"], kwargs["root_name"]))
        return self.setup_error

    def get_acquired_image(self, **kwargs):
        self.calls.append(("acquire", kwargs["exposure"]))
        self.release.wait(5)  # simulate the exposure still running
        w, h = kwargs["width"], kwargs["height"]
        return w, h, bytes(2 * w * h)

    def get_file_save_result(self):
        self.calls.append(("result",))
        return self.num_saved, 0


async def _wait_idle(acq: AcquisitionController) -> None:
    for _ in range(500):
        if not acq.dose_frac_busy.get():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("dose-fractionated exposure never finished")


async def _configured(conn: _FakeConnection) -> AcquisitionController:
    acq = AcquisitionController(conn)  # type: ignore[arg-type]
    await acq.width.update(8)
    await acq.height.update(4)
    await acq.save_dir.update("D:\\frames")
    await acq.save_root_name.update("movie_0001")
    await acq.dose_frac_num_frames.update(20)
    await acq.dose_frac_exposure.update(1.0)
    return acq


@pytest.mark.asyncio
async def test_dose_fractionated_exposure_reports_status_and_path():
    conn = _FakeConnection()
    acq = await _configured(conn)

    await acq.acquire_dose_fractionated()
    # the command returns while the exposure is still running
    assert acq.dose_frac_busy.get() is True
    assert acq.dose_frac_state.get() is DoseFracState.ACQUIRING
    with pytest.raises(RuntimeError, match="already running"):
        await acq.acquire_dose_fractionated()

    conn.release.set()
    await _wait_idle(acq)

    assert acq.dose_frac_state.get() is DoseFracState.DONE
    assert acq.frames_saved.get() == 20
    assert acq.saved_path.get() == "D:\\frames\\movie_0001.mrc"
    assert conn.calls == [
        ("k2", True, 0.05),
        ("setup", "D:\\frames", "movie_0001"),
        ("acquire", 1.0),
        ("result",),
        ("k2", False, 0.0),  # frame saving disarmed afterwards
    ]


@pytest.mark.asyncio
async def test_dose_fractionated_setup_error_fails_without_acquiring():
    conn = _FakeConnection(setup_error=15)
    acq = await _configured(conn)

    await acq.acquire_dose_fractionated()
    await _wait_idle(acq)

    assert acq.dose_frac_state.get() is DoseFracState.FAILED
    assert "DIR_NOT_WRITABLE" in acq.dose_frac_message.get()
    assert acq.saved_path.get() == ""
    assert [c[0] for c in conn.calls] == ["k2", "setup", "k2"]


@pytest.mark.asyncio
async def test_dose_fractionated_frame_count_mismatch_is_reported():
    conn = _FakeConnection(num_saved=18)
    conn.release.set()
    acq = await _configured(conn)

    await acq.acquire_dose_fractionated()
    await _wait_idle(acq)

    assert acq.dose_frac_state.get() is DoseFracState.DONE
    assert acq.frames_saved.get() == 18
    assert "requested 20 frames, camera saved 18" in acq.dose_frac_message.get()
