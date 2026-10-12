"""Camera enumeration / selection / insertion — SCAFFOLD.

Attribute and command shapes are settled (mirrors the approved v1 scope's
"full camera select+query support"); the bodies call through to
:class:`~fastcs_gatan.connection.GatanSocketConnection`, which is itself not
yet implemented (see that module's docstring) — so nothing here runs yet.
"""

from __future__ import annotations

import asyncio

from fastcs.attributes import AttrR, AttrRW
from fastcs.controllers import Controller
from fastcs.datatypes import Bool, Int
from fastcs.methods import command

from fastcs_gatan.connection import GatanSocketConnection

INSERTION_GROUP = "Insertion"


class CameraController(Controller):
    """Camera enumeration, selection, and insertion state.

    Insertion is slow (~10 s measured on a K3 by GatanDetectorClient's own
    testing) and moves real hardware, so ``insert``/``retract`` poll for the
    resulting state rather than blocking on a single wait — same shape as
    fastcs-eiger's ``arm_when_ready``.
    """

    num_cameras = AttrR(Int(), description="Number of cameras reported by DM")
    current_camera = AttrRW(Int(min=0), initial_value=0)
    inserted = AttrR(Bool(), group=INSERTION_GROUP)
    insertion_timeout = AttrRW(
        Int(min=1),
        initial_value=30,
        description="Seconds to wait for insert/retract",
        group=INSERTION_GROUP,
    )
    insertion_poll_period = AttrRW(
        Int(min=1),
        initial_value=1,
        description="Seconds between insertion-state polls",
        group=INSERTION_GROUP,
    )

    def __init__(self, connection: GatanSocketConnection) -> None:
        super().__init__()
        self._connection = connection

    async def initialise(self) -> None:
        await self.num_cameras.update(self._connection.get_number_of_cameras())
        await self._refresh_inserted()

    async def _refresh_inserted(self) -> None:
        state = self._connection.is_camera_inserted(self.current_camera.get())
        await self.inserted.update(state)

    @command()
    async def select(self) -> None:
        """Select ``current_camera`` as the active camera for subsequent
        calls, via ``SET_CURRENT_CAMERA`` (matches
        ``CameraBackend.set_current_camera``'s call site in
        GatanDetectorClient's own adapter; ``SELECT_CAMERA`` also exists on
        the connection as a lower-level alternative if this turns out wrong
        against real hardware)."""
        self._connection.set_current_camera(self.current_camera.get())

    async def _set_insertion(self, want: bool) -> None:
        self._connection.insert_camera(self.current_camera.get(), want)
        timeout = self.insertion_timeout.get()
        poll = self.insertion_poll_period.get()
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(poll)
            elapsed += poll
            await self._refresh_inserted()
            if self.inserted.get() is want:
                return
        raise TimeoutError(
            f"camera {self.current_camera.get()} did not reach "
            f"inserted={want} within {timeout}s"
        )

    @command(group=INSERTION_GROUP)
    async def insert(self) -> None:
        await self._set_insertion(True)

    @command(group=INSERTION_GROUP)
    async def retract(self) -> None:
        await self._set_insertion(False)
