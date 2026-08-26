[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# FastCS Gatan

Control system integration for Gatan K3 detectors using [FastCS](https://github.com/DiamondLightSource/fastcs), modeled on [fastcs-eiger](https://github.com/DiamondLightSource/fastcs-eiger).

**Status: scaffold only.** The controller/attribute shape is in place; the
GatanSocket wire-protocol client
(`src/fastcs_gatan/connection/gatan_socket.py`) is not implemented yet — see
that module's docstring for the plan and `CLAUDE.md` for the full scope
decision.

fastcs-gatan speaks the TCP/IP "GatanSocket" protocol used by the
SerialEMCCD DigitalMicrograph plugin directly — it does **not** depend on
[`GatanDetectorClient`](https://github.com/DiamondLightSource) as a package,
though that project's `gatan_socket.py` (Apache-2.0) is the porting basis for
this repo's own implementation, cross-checked against the MIT-licensed
client-side protocol code in
[SerialEM](https://github.com/mastcu/SerialEM).

Supported acquisition modes (v1 scope): single-frame acquisition, continuous
acquisition, and dose-fractionation where sub-frames are written to storage
on the server (DM) side only — never transferred over the socket. Also in
scope: full camera enumeration/selection/insertion and full K2/K3
read-mode/parameter select+query support.

Source          | <https://github.com/DiamondLightSource/fastcs-gatan>
:---:           | :---:
PyPI            | `pip install fastcs-gatan`
Docker          | `docker run ghcr.io/diamondlightsource/fastcs-gatan:latest`

<!-- README only content. Anything below this line won't be included in index.md -->

See `CLAUDE.md` for architecture and the current scope decision, and
`/workspaces/CLAUDE.md` for how this repo relates to its siblings
(`fastcs`, `fastcs-eiger`, `GatanDetectorClient-0.1.0`, `SerialEM`,
`SerialEMCCD`).
