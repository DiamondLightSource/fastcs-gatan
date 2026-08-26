"""Structural smoke tests for the controllers — construction and wiring only.

Real wire-protocol behavior (connect, status queries, camera select/insert,
read-mode, single-frame acquisition) is exercised against a loopback socket
pair in test_gatan_socket_wire.py. ``GatanController.initialise()`` isn't
called here since it needs a live socket; K2/K3 parameter config, continuous
acquisition, and dose-fractionation-to-disk are still unimplemented stubs on
the connection (see fastcs_gatan/connection/gatan_socket.py) and so aren't
covered yet either.
"""

from fastcs.connections import IPConnectionSettings

from fastcs_gatan.controllers.gatan_controller import GatanController


def test_construct_controller():
    controller = GatanController(
        connection_settings=IPConnectionSettings(ip="127.0.0.1", port=48890)
    )
    assert controller.connection.host == "127.0.0.1"
    assert controller.connection.port == 48890
    assert controller.connection.connected is False


def test_deferred_features_still_raise_not_implemented():
    """K2/K3 params, continuous, and dose-frac-to-disk are explicitly out of
    scope for this session — pin that they still fail loudly rather than
    silently doing the wrong thing."""
    controller = GatanController(
        connection_settings=IPConnectionSettings(ip="127.0.0.1", port=48890)
    )
    conn = controller.connection
    for call in (
        lambda: conn.set_k2_parameters2(0, 1.0, 0, False, 0.05, False, False, 0, 0),
        conn.stop_continuous_camera,
        lambda: conn.setup_file_saving2(0, False, 1.0, 0, "", ""),
        conn.get_file_save_result,
    ):
        try:
            call()
        except NotImplementedError:
            pass
        else:
            raise AssertionError(f"{call} no longer raises NotImplementedError")
