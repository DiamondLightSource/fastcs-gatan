"""Read-only probe of a real SerialEMCCD plugin through the fastcs-gatan driver.

Builds ``GatanController`` from a fastcs YAML config and runs its
``initialise()``, the same startup the IOC does, then prints the camera's basic
information. Every call is a query: nothing is acquired, inserted, selected
or configured.

    python examples/probe_real_server.py Talos_K3.yaml
    python examples/probe_real_server.py --host 10.184.8.4 --port 48890

Calls made, all read-only:
    initialise(): GetDMVersion, GetPluginVersion, GetLastError, GetLastDoseRate,
                  GetNumberOfCameras, IsCameraInserted(0)
    then:         GetDMVersionAndBuild, GetDMCapabilities, IsCameraInserted(i)

The plugin serves one client at a time: don't run this while a SerialEM
session is using the same port.

Modeled on GatanDetectorClient's examples/probe_real_server.py (read-only
sweep only; no acquisition option).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import yaml
from fastcs.connections import IPConnectionSettings

from fastcs_gatan.connection.gatan_socket import SEMCCD_ERRORS, GatanSocketError
from fastcs_gatan.controllers.gatan_controller import GatanController

T = TypeVar("T")


def _target(args: argparse.Namespace) -> tuple[str, int]:
    """Host/port from --host/--port, else from the first controller in the YAML."""
    if args.host:
        return args.host, args.port
    if not args.config:
        raise SystemExit("give a YAML config or --host")
    entry = yaml.safe_load(Path(args.config).read_text())["controllers"][0]
    return entry["ip"], int(entry.get("port", args.port))


def _row(label: str, value: object) -> None:
    print(f"  {label:24s} {value}")


def _query(label: str, call: Callable[[], T], errors: dict[str, str]) -> T | None:
    try:
        return call()
    except GatanSocketError as exc:
        errors[label] = str(exc)
        return None


async def probe(host: str, port: int) -> int:
    print(f"connecting to SerialEMCCD plugin at {host}:{port} ...")
    controller = GatanController(IPConnectionSettings(ip=host, port=port))
    conn = controller.connection
    try:
        await controller.initialise()  # connect + the driver's startup queries
        print("connected. read-only probe:\n")
        errors: dict[str, str] = {}

        _row("DM version", controller.dm_version.get())
        build = _query("GetDMVersionAndBuild", conn.get_dm_version_and_build, errors)
        if build:
            _row("DM version / build", f"{build[0]} / {build[1]}")
        _row("plugin version", controller.plugin_version.get())

        caps = _query("GetDMCapabilities", conn.get_dm_capabilities, errors)
        if caps:
            _row("can select shutter", caps[0])
            _row("can set settling", caps[1])
            _row("open-shutter works", caps[2])

        num = controller.camera.num_cameras.get()
        _row("number of cameras", num)
        inserted = {
            i: _query(
                f"IsCameraInserted({i})", lambda i=i: conn.is_camera_inserted(i), errors
            )
            for i in range(num)
        }
        _row("cameras inserted", ", ".join(f"{i}:{v}" for i, v in inserted.items()))

        err = controller.last_error.get()
        name = SEMCCD_ERRORS.get(abs(err), "unknown") if err else "none"
        _row("last error", f"{err} ({name})")
        _row("last dose rate", controller.last_dose_rate.get())

        if errors:
            print("  unsupported / errored calls:")
            for label, text in errors.items():
                print(f"    - {label}: {text}")
        print(
            "\nread-only probe complete: no camera state changed, "
            "no acquisition performed."
        )
        return 0
    except (OSError, GatanSocketError) as exc:
        print(f"probe failed: {exc}")
        return 1
    finally:
        conn.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("config", nargs="?", help="fastcs YAML config, e.g. Talos_K3.yaml")
    ap.add_argument("--host", help="plugin host/IP (overrides the config)")
    ap.add_argument("--port", type=int, default=48890, help="plugin port")
    args = ap.parse_args()
    return asyncio.run(probe(*_target(args)))


if __name__ == "__main__":
    raise SystemExit(main())
