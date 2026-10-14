"""Print a Gatan camera's basic information through fastcs-gatan's REST interface.

Only reads (HTTP GET); nothing is changed on the driver or the camera.

1. Start the driver (it connects to the SerialEMCCD plugin and reads its status):

       python -m fastcs_gatan run Talos_K3.yaml

2. In another terminal:

       python examples/query_basic_info.py            # controller id TALOS-K3
       python examples/query_basic_info.py GATAN      # e.g. with gatan.yaml

The driver reads these values once, when it starts; they are not refreshed
afterwards.
"""

import json
import sys
import urllib.request

BASE = "http://localhost:8080"

# (label, path under the controller id)
FIELDS = [
    ("DM version", "dm-version"),
    ("plugin version", "plugin-version"),
    ("last error", "last-error"),
    ("last dose rate", "last-dose-rate"),
    ("number of cameras", "camera/num-cameras"),
    ("current camera", "camera/current-camera"),
    ("current camera inserted", "camera/inserted"),
]


def get(path: str) -> object:
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=5) as response:
        return json.load(response)["value"]


def main() -> int:
    controller_id = sys.argv[1] if len(sys.argv) > 1 else "TALOS-K3"
    print(f"{controller_id} via {BASE}")
    for label, path in FIELDS:
        try:
            value = get(f"{controller_id}/{path}")
        except OSError as exc:
            print(f"  {label:24s} unavailable ({exc})")
            continue
        print(f"  {label:24s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
