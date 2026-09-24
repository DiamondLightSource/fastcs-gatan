[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# FastCS Gatan

A Gatan K3 detector driver in [FastCS](https://github.com/DiamondLightSource/fastcs), acting as a client to the SerialEMCCD plugin on the DigitalMicrograph (DM) computer. Modeled on [fastcs-eiger](https://github.com/DiamondLightSource/fastcs-eiger).

**Status: in development, not yet tested on hardware.** Tested against unit
tests and GatanDetectorClient's mock server only.

- **Working**: connection and status (DM/plugin version, last error, dose
  rate); camera enumeration, selection, insertion and retraction; read mode
  and K2/K3 parameters; single-frame acquisition; dose-fractionated
  acquisition with frames saved on the DM computer only (the driver gets back
  a summed image, the saved-frame count and the file path).
- **Not yet implemented**: continuous acquisition.

See [Example 1](docs/examples/01_dose_fractionation.md) for running a
dose-fractionated exposure over REST and EPICS against the mock server.

fastcs-gatan implements the TCP/IP "GatanSocket" protocol of the SerialEMCCD
plugin itself. It does **not** depend on
[`GatanDetectorClient`](https://github.com/DiamondLightSource) as a package,
though that project's `gatan_socket.py` (Apache-2.0) is the porting basis.
Calls are cross-checked against the MIT-licensed client code in
[SerialEM](https://github.com/mastcu/SerialEM); the K2/K3 parameter and
frame-saving calls were also checked against how the
[SerialEMCCD](https://github.com/mastcu/SerialEMCCD) plugin unpacks them
(GPL-2, read only, no code copied).

Out of scope for now: dark/gain reference acquisition, DM scripting,
DigiScan/STEM and frame alignment.

Source          | <https://github.com/DiamondLightSource/fastcs-gatan>
:---:           | :---:
PyPI            | `pip install fastcs-gatan`
Docker          | `docker run ghcr.io/diamondlightsource/fastcs-gatan:latest`

<!-- README only content. Anything below this line won't be included in index.md -->

See `CLAUDE.md` for architecture and the current scope decision, and
`/workspaces/CLAUDE.md` for how this repo relates to its siblings
(`fastcs`, `fastcs-eiger`, `GatanDetectorClient-0.1.0`, `SerialEM`,
`SerialEMCCD`).
