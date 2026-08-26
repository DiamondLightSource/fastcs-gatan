"""Root controller for the Gatan K3 driver — SCAFFOLD.

Mirrors fastcs-eiger's root-controller shape (owns the connection, exposes
top-level status attributes, adds subsystem sub-controllers), narrowed to the
approved v1 scope. See ``fastcs_gatan.connection.gatan_socket`` for what
still needs implementing before any of this actually talks to hardware.
"""

from __future__ import annotations

from fastcs.attributes import AttrR
from fastcs.connections import IPConnectionSettings
from fastcs.controllers import Controller
from fastcs.datatypes import Float, Int

from fastcs_gatan.connection import GatanSocketConnection
from fastcs_gatan.controllers.acquisition_controller import AcquisitionController
from fastcs_gatan.controllers.camera_controller import CameraController

STATUS_GROUP = "Status"


class GatanController(Controller):
    """Root controller for a Gatan K3 detector, talking GatanSocket over TCP.

    Args:
        connection_settings: IP/port of the SerialEMCCD plugin's GatanSocket
            server (conventionally port 48890).
    """

    camera: CameraController
    acquisition: AcquisitionController

    dm_version = AttrR(Int(), group=STATUS_GROUP)
    plugin_version = AttrR(Int(), group=STATUS_GROUP)
    last_error = AttrR(Int(), group=STATUS_GROUP)
    last_dose_rate = AttrR(Float(), group=STATUS_GROUP)

    def __init__(self, connection_settings: IPConnectionSettings) -> None:
        super().__init__()
        self.connection_settings = connection_settings
        self.connection = GatanSocketConnection(
            host=connection_settings.ip, port=connection_settings.port
        )

    async def initialise(self) -> None:
        """Connect and populate read-only status attributes.

        Mirrors EigerController.initialise()'s introspection-on-connect
        pattern, but there is no self-describing parameter list to
        introspect here — the attribute set is fixed at class-definition
        time, so this just connects and reads status/capabilities.
        """
        self.connection.connect()

        await self.dm_version.update(self.connection.get_dm_version())
        await self.plugin_version.update(self.connection.get_plugin_version())
        await self.last_error.update(self.connection.get_last_error())
        await self.last_dose_rate.update(self.connection.get_last_dose_rate())

        camera = CameraController(self.connection)
        await camera.initialise()
        self.add_sub_controller("camera", camera)

        acquisition = AcquisitionController(self.connection)
        self.add_sub_controller("acquisition", acquisition)
