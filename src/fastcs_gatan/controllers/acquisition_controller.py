"""Read-mode/K2-K3 configuration and the three approved acquisition modes.
Single-frame and dose-fractionated acquisition are implemented; continuous
acquisition is still a placeholder.

In scope (per the 2026-08-17 scope decision): single-frame acquisition,
continuous acquisition, and dose-fractionation where sub-frames are written
to storage on the server (DM) side only — never transferred over the socket.
Dark/gain reference acquisition is out of scope for now.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass

import numpy as np
from fastcs.attributes import AttrR, AttrRW
from fastcs.controllers import Controller
from fastcs.datatypes import Bool, Enum, Float, Int, String, Waveform
from fastcs.methods import command

from fastcs_gatan.connection import GatanSocketConnection
from fastcs_gatan.connection.gatan_socket import (
    SEMCCD_ERRORS,
    GatanSocketError,
    saved_frames_path,
)

MODE_GROUP = "ReadMode"
ACQUIRE_GROUP = "Acquire"
CONTINUOUS_GROUP = "Continuous"
SAVING_GROUP = "FrameSaving"

# TODO: this is a placeholder cap, not a real sensor size — replace once a
# camera config lookup (cf. GatanDetectorClient's cameras.json) exists.
_MAX_FRAME_SHAPE = (4096, 4096)


class DoseFracState(enum.Enum):
    IDLE = "Idle"
    ACQUIRING = "Acquiring"
    DONE = "Done"
    FAILED = "Failed"


@dataclass(frozen=True)
class _DoseFracRequest:
    """Snapshot of every attribute a dose-fractionated exposure reads, taken
    on the event loop before handing off to the worker thread."""

    num_frames: int
    exposure: float
    save_dir: str
    root_name: str
    pixel_size: float
    save_flags: int
    read_mode: int
    scaling: float
    hardware_proc: int
    rotation_flip: int
    width: int
    height: int
    processing: int
    binning: int
    shutter: int

    @property
    def frame_time(self) -> float:
        return self.exposure / self.num_frames


@dataclass(frozen=True)
class _DoseFracResult:
    num_saved: int
    save_error: int
    width: int
    height: int
    raw: bytes


class AcquisitionController(Controller):
    # ---- Read mode / K2-K3 parameter select+query ----
    read_mode = AttrRW(Int(), group=MODE_GROUP, description="K2/K3 read mode")
    scaling = AttrRW(Float(), initial_value=1.0, group=MODE_GROUP)
    hardware_proc = AttrRW(Int(), initial_value=0, group=MODE_GROUP)
    align_frames = AttrRW(
        Bool(),
        initial_value=False,
        group=MODE_GROUP,
        description="Frame alignment: out of scope, keep off",
    )
    rotation_flip = AttrRW(Int(), initial_value=0, group=MODE_GROUP)

    # ---- Single-frame / continuous acquisition parameters ----
    width = AttrRW(Int(min=1), initial_value=1024, group=ACQUIRE_GROUP)
    height = AttrRW(Int(min=1), initial_value=1024, group=ACQUIRE_GROUP)
    exposure = AttrRW(Float(min=0), initial_value=0.1, group=ACQUIRE_GROUP)
    binning = AttrRW(Int(min=1), initial_value=1, group=ACQUIRE_GROUP)
    processing = AttrRW(
        Int(),
        initial_value=0,
        group=ACQUIRE_GROUP,
        description="0=unprocessed 1=dark-sub 2=gain-norm",
    )
    shutter = AttrRW(Int(), initial_value=0, group=ACQUIRE_GROUP)
    last_frame = AttrR(
        Waveform(array_dtype=np.uint16, shape=_MAX_FRAME_SHAPE),
        group=ACQUIRE_GROUP,
        description="Most recently acquired single frame",
    )

    # ---- Continuous acquisition ----
    continuous_quality = AttrRW(
        Int(min=0, max=7), initial_value=0, group=CONTINUOUS_GROUP
    )
    continuous_active = AttrR(Bool(), group=CONTINUOUS_GROUP)

    # ---- Dose fractionation to server-side storage only ----
    # Inputs for acquire_dose_fractionated. Frames go to one uncompressed MRC
    # stack on the DM machine unless save_format_flags says otherwise.
    dose_frac_num_frames = AttrRW(Int(min=1), initial_value=40, group=SAVING_GROUP)
    dose_frac_exposure = AttrRW(
        Float(min=0),
        initial_value=2.0,
        group=SAVING_GROUP,
        description="Total exposure (s), split over frames",
    )
    dose_frac_state = AttrR(Enum(DoseFracState), group=SAVING_GROUP)
    dose_frac_busy = AttrR(
        Bool(), group=SAVING_GROUP, description="True until the exposure ends"
    )
    dose_frac_message = AttrR(String(), group=SAVING_GROUP)
    saved_path = AttrR(
        String(),
        group=SAVING_GROUP,
        description="Frame file of last exposure, on DM PC",
    )
    dose_frac = AttrRW(Bool(), initial_value=False, group=SAVING_GROUP)
    frame_time = AttrRW(Float(min=0), initial_value=0.05, group=SAVING_GROUP)
    save_frames = AttrRW(Bool(), initial_value=False, group=SAVING_GROUP)
    save_dir = AttrRW(
        String(),
        initial_value="",
        group=SAVING_GROUP,
        description="Folder on the DM PC, not this IOC",
    )
    save_root_name = AttrRW(String(), initial_value="gatan", group=SAVING_GROUP)
    save_pixel_size = AttrRW(Float(min=0), initial_value=1.0, group=SAVING_GROUP)
    save_format_flags = AttrRW(Int(), initial_value=0, group=SAVING_GROUP)
    frames_saved = AttrR(Int(), group=SAVING_GROUP)
    save_error = AttrR(Int(), group=SAVING_GROUP)

    def __init__(self, connection: GatanSocketConnection) -> None:
        super().__init__()
        self._connection = connection
        self._dose_frac_task: asyncio.Task[None] | None = None

    async def _update_last_frame(self, width: int, height: int, raw: bytes) -> None:
        # TODO: raw is a bytes buffer from the wire; decode with the correct
        # signed/unsigned dtype (see the fastcs-gatan memory notes on the
        # signed/unsigned 16-bit ambiguity in this protocol) before storing.
        frame = np.frombuffer(raw, dtype=np.uint16).reshape(height, width)
        await self.last_frame.update(frame)

    @command(group=MODE_GROUP)
    async def apply_read_mode(self) -> None:
        self._connection.set_read_mode(self.read_mode.get(), self.scaling.get())

    @command(group=MODE_GROUP)
    async def apply_k2_parameters(self) -> None:
        self._connection.set_k2_parameters2(
            read_mode=self.read_mode.get(),
            scaling=self.scaling.get(),
            hardware_proc=self.hardware_proc.get(),
            dose_frac=self.dose_frac.get(),
            frame_time=self.frame_time.get(),
            align_frames=self.align_frames.get(),
            save_frames=self.save_frames.get(),
            rotation_flip=self.rotation_flip.get(),
            flags=0,
        )

    @command(group=ACQUIRE_GROUP)
    async def acquire_image(self) -> None:
        """Single-frame acquisition."""
        w, h, raw = self._connection.get_acquired_image(
            width=self.width.get(),
            height=self.height.get(),
            processing=self.processing.get(),
            exposure=self.exposure.get(),
            binning=self.binning.get(),
            shutter=self.shutter.get(),
        )
        await self._update_last_frame(w, h, raw)

    @command(group=CONTINUOUS_GROUP)
    async def start_continuous(self) -> None:
        """Continuous acquisition: OR continuous-mode bits into `processing`
        and repeatedly call GetAcquiredImage until stopped. TODO: this needs
        an async loop (fastcs `@scan` or a background task), not a single
        call — placeholder only."""
        await self.continuous_active.update(True)
        raise NotImplementedError

    @command(group=CONTINUOUS_GROUP)
    async def stop_continuous(self) -> None:
        self._connection.stop_continuous_camera()
        await self.continuous_active.update(False)

    @command(group=SAVING_GROUP)
    async def acquire_dose_fractionated(self) -> None:
        """Start a dose-fractionated exposure: ``dose_frac_exposure`` seconds
        split into ``dose_frac_num_frames`` frames, all written to storage
        on the DM machine only (never sent over this socket).

        Returns straight away; poll ``dose_frac_busy``/``dose_frac_state``
        for completion, then read ``saved_path`` and ``frames_saved``. The
        summed image is put in ``last_frame``.
        """
        if self.dose_frac_busy.get():
            raise RuntimeError("a dose-fractionated exposure is already running")
        if not self.save_dir.get():
            raise ValueError("save_dir must be set (a path on the DM machine)")
        request = _DoseFracRequest(
            num_frames=self.dose_frac_num_frames.get(),
            exposure=self.dose_frac_exposure.get(),
            save_dir=self.save_dir.get(),
            root_name=self.save_root_name.get(),
            pixel_size=self.save_pixel_size.get(),
            save_flags=self.save_format_flags.get(),
            read_mode=self.read_mode.get(),
            scaling=self.scaling.get(),
            hardware_proc=self.hardware_proc.get(),
            rotation_flip=self.rotation_flip.get(),
            width=self.width.get(),
            height=self.height.get(),
            processing=self.processing.get(),
            binning=self.binning.get(),
            shutter=self.shutter.get(),
        )
        if request.exposure <= 0:
            raise ValueError("dose_frac_exposure must be positive")

        await self.dose_frac_busy.update(True)
        await self.dose_frac_state.update(DoseFracState.ACQUIRING)
        await self.dose_frac_message.update("")
        await self.saved_path.update("")
        await self.frames_saved.update(0)
        await self.save_error.update(0)
        self._dose_frac_task = asyncio.create_task(self._run_dose_frac(request))

    async def _run_dose_frac(self, request: _DoseFracRequest) -> None:
        try:
            result = await asyncio.to_thread(self._dose_frac_sequence, request)
        except Exception as e:
            await self.dose_frac_message.update(str(e))
            await self.dose_frac_state.update(DoseFracState.FAILED)
            await self.dose_frac_busy.update(False)
            return

        await self.frames_saved.update(result.num_saved)
        await self.save_error.update(result.save_error)
        if result.num_saved:
            await self.saved_path.update(
                saved_frames_path(
                    request.save_dir, request.root_name, request.save_flags
                )
            )
        if result.save_error:
            name = SEMCCD_ERRORS.get(result.save_error, "unknown")
            await self.dose_frac_message.update(
                f"frame saving error {result.save_error} ({name}); "
                f"{result.num_saved} frames saved"
            )
            await self.dose_frac_state.update(DoseFracState.FAILED)
        else:
            if result.num_saved != request.num_frames:
                # The camera silently clamps frame times it can't achieve.
                await self.dose_frac_message.update(
                    f"requested {request.num_frames} frames, "
                    f"camera saved {result.num_saved}"
                )
            await self.dose_frac_state.update(DoseFracState.DONE)
        try:
            await self._update_last_frame(result.width, result.height, result.raw)
        except Exception as e:
            await self.dose_frac_message.update(f"summed image not stored: {e}")
        finally:
            await self.dose_frac_busy.update(False)

    def _dose_frac_sequence(self, request: _DoseFracRequest) -> _DoseFracResult:
        """Blocking wire sequence, run in a worker thread holding the
        connection: SetK2Parameters2 -> SetupFileSaving2 -> GetAcquiredImage
        (blocks until the exposure and saving finish) -> GetFileSaveResult.
        Same order as SerialEM's ``CameraController``."""
        conn = self._connection

        def set_k2(dose_frac: bool) -> None:
            conn.set_k2_parameters2(
                read_mode=request.read_mode,
                scaling=request.scaling,
                hardware_proc=request.hardware_proc,
                dose_frac=dose_frac,
                frame_time=request.frame_time if dose_frac else 0.0,
                align_frames=False,
                save_frames=dose_frac,
                rotation_flip=request.rotation_flip,
                flags=0,
            )

        with conn.exclusive():
            set_k2(True)
            try:
                err = conn.setup_file_saving2(
                    rotation_flip=request.rotation_flip,
                    file_per_image=False,
                    pixel_size=request.pixel_size,
                    flags=request.save_flags,
                    save_dir=request.save_dir,
                    root_name=request.root_name,
                )
                if err:
                    name = SEMCCD_ERRORS.get(err, "unknown")
                    raise GatanSocketError(
                        f"SetupFileSaving2 failed: error {err} ({name})"
                    )
                width, height, raw = conn.get_acquired_image(
                    width=request.width,
                    height=request.height,
                    processing=request.processing,
                    exposure=request.exposure,
                    binning=request.binning,
                    shutter=request.shutter,
                )
                num_saved, save_error = conn.get_file_save_result()
            finally:
                # Don't leave frame saving armed for the next single-frame
                # acquire_image; a failure here must not hide the real error.
                try:
                    set_k2(False)
                except GatanSocketError:
                    pass
        return _DoseFracResult(num_saved, save_error, width, height, raw)
