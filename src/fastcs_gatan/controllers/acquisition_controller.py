"""Read-mode/K2-K3 configuration and the three approved acquisition modes —
SCAFFOLD. See ``fastcs_gatan.connection.gatan_socket`` for what's actually
implemented (nothing yet); this module settles the attribute/command shape.

In scope (per the 2026-08-17 scope decision): single-frame acquisition,
continuous acquisition, and dose-fractionation where sub-frames are written
to storage on the server (DM) side only — never transferred over the socket.
Dark/gain reference acquisition is out of scope for now.
"""

from __future__ import annotations

import numpy as np
from fastcs.attributes import AttrR, AttrRW
from fastcs.controllers import Controller
from fastcs.datatypes import Bool, Float, Int, String, Waveform
from fastcs.methods import command

from fastcs_gatan.connection import GatanSocketConnection

MODE_GROUP = "ReadMode"
ACQUIRE_GROUP = "Acquire"
CONTINUOUS_GROUP = "Continuous"
SAVING_GROUP = "FrameSaving"

# TODO: this is a placeholder cap, not a real sensor size — replace once a
# camera config lookup (cf. GatanDetectorClient's cameras.json) exists.
_MAX_FRAME_SHAPE = (4096, 4096)


class AcquisitionController(Controller):
    # ---- Read mode / K2-K3 parameter select+query ----
    read_mode = AttrRW(Int(), group=MODE_GROUP, description="K2/K3 read mode")
    scaling = AttrRW(Float(), initial_value=1.0, group=MODE_GROUP)
    hardware_proc = AttrRW(Int(), initial_value=0, group=MODE_GROUP)
    align_frames = AttrRW(
        Bool(),
        initial_value=False,
        group=MODE_GROUP,
        description="Frame alignment is out of v1 scope — keep False",
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
        description="GetAcquiredImage processing flags (gain-normalised etc.)",
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
    dose_frac = AttrRW(Bool(), initial_value=False, group=SAVING_GROUP)
    frame_time = AttrRW(Float(min=0), initial_value=0.05, group=SAVING_GROUP)
    save_frames = AttrRW(Bool(), initial_value=False, group=SAVING_GROUP)
    save_dir = AttrRW(
        String(),
        initial_value="",
        group=SAVING_GROUP,
        description="Path ON THE DM MACHINE — not local to this IOC",
    )
    save_root_name = AttrRW(String(), initial_value="gatan", group=SAVING_GROUP)
    save_pixel_size = AttrRW(Float(min=0), initial_value=1.0, group=SAVING_GROUP)
    save_format_flags = AttrRW(Int(), initial_value=0, group=SAVING_GROUP)
    frames_saved = AttrR(Int(), group=SAVING_GROUP)
    save_error = AttrR(Int(), group=SAVING_GROUP)

    def __init__(self, connection: GatanSocketConnection) -> None:
        super().__init__()
        self._connection = connection

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
        _w, _h, raw = self._connection.get_acquired_image(
            width=self.width.get(),
            height=self.height.get(),
            processing=self.processing.get(),
            exposure=self.exposure.get(),
            binning=self.binning.get(),
            shutter=self.shutter.get(),
        )
        # TODO: raw is a bytes buffer from the wire; decode with the correct
        # signed/unsigned dtype (see the fastcs-gatan memory notes on the
        # signed/unsigned 16-bit ambiguity in this protocol) before storing.
        frame = np.frombuffer(raw, dtype=np.uint16).reshape(_h, _w)
        await self.last_frame.update(frame)

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
        """Dose-fractionated acquisition with sub-frames written to storage
        on the DM machine only — no per-sub-frame network transfer.

        Sequence: configure file saving -> set K2/K3 params with
        dose_frac=True, save_frames=True -> one GetAcquiredImage call ->
        GetFileSaveResult for the actual saved-frame count/error.
        """
        err = self._connection.setup_file_saving2(
            rotation_flip=self.rotation_flip.get(),
            file_per_image=False,
            pixel_size=self.save_pixel_size.get(),
            flags=self.save_format_flags.get(),
            save_dir=self.save_dir.get(),
            root_name=self.save_root_name.get(),
        )
        if err:
            await self.save_error.update(err)
            raise RuntimeError(f"SetupFileSaving2 failed with error {err}")

        await self.apply_k2_parameters()
        await self.acquire_image()

        num_saved, save_err = self._connection.get_file_save_result()
        await self.frames_saved.update(num_saved)
        await self.save_error.update(save_err)
