from fastcs.launch import launch

from fastcs_gatan import __version__
from fastcs_gatan.controllers.gatan_controller import GatanController

__all__ = ["main"]


def main() -> None:
    """CLI entry point.

    Uses ``fastcs.launch.launch``, which introspects ``GatanController``'s
    type-hinted ``__init__`` to generate a CLI with ``schema`` (print the
    config schema) and ``run <config.yaml>`` subcommands — the transport(s)
    and ``connection_settings`` (IP/port of the GatanSocket server) are
    supplied via that YAML file, not as CLI flags.

    NOTE: this follows the *current* local `fastcs` checkout's API
    (`/workspaces/fastcs`), not `fastcs-eiger`'s `__main__.py`, which was
    written against an older, pinned fastcs release with a different launch
    API (a manual `typer` `ioc` command building an `EpicsCATransport`
    directly). Re-check against `fastcs.launch` if this drifts again.
    """
    launch(GatanController, version=__version__)


# test with: python -m fastcs_gatan
if __name__ == "__main__":
    main()
