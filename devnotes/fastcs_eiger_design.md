# fastcs-eiger design notes

Studied 2026-10-12 at fastcs-eiger commit `21ea034` ("Update to fastcs 0.14.0"), as a
reference for fastcs-gatan. Paths are relative to `fastcs-eiger/src/fastcs_eiger/`.

## Overview

fastcs-eiger controls a Dectris Eiger detector through the detector's own web API
(SIMPLON), using an aiohttp-based `HTTPConnection` (`http_connection.py`). It starts
with the same `launch()` idiom as fastcs-gatan (`__main__.py`), registering
`EigerController` and `EigerOdinController`; example configs are
`fastcs-eiger.yaml` and `fastcs-eiger-odin.yaml`.

The SIMPLON API is split into three subsystems: `detector`, `monitor` and `stream`.
fastcs-eiger mirrors that split with one sub-controller per subsystem under the root
controller, so parameters appear as `<id>:Detector:...`, `<id>:Monitor:...` and
`<id>:Stream:...`.

## Root controller: `EigerController` (`controllers/eiger_controller.py`)

- Owns the HTTP connection and an update queue (an `asyncio.Queue` of refresh
  coroutines, guarded by a lock).
- `initialise()` creates the three subsystem controllers. If the detector reports
  state `na`, it sends `initialize` first.
- A `@scan(0.1)` method, `update()`, empties the queue and refreshes the queued
  parameters. The `stale_parameters` flag is true while anything is queued.
- `arm_when_ready` waits until `stale_parameters` is false (timeout `arm_timeout`),
  then arms, so the detector is never armed with out-of-date settings.

## Shared base class: `EigerSubsystemController` (`controllers/eiger_subsystem_controller.py`)

Most of the work is here. Parameters are not written in the code: each subsystem
controller asks the detector for them at startup.

1. **Ask what exists.** GET `<subsystem>/api/<version>/status/keys` and
   `.../config/keys`: the read-only status values and the settable config values.
2. **Filter.** Drop `IGNORED_KEYS` (big arrays such as pixel masks, deprecated values,
   array-valued settings) and add `MISSING_KEYS` (parameters the API forgets to list).
3. **Build attributes.** GET each key once. The JSON reply gives the value type
   (float/int/bool/string), whether it is read-only or writable, and a minimum, which
   sets the number of decimal places. Each becomes an `AttrR` or `AttrRW`
   (`eiger_parameter.py`, `EigerParameterRef`). Groups come from the key path
   (`threshold/1/energy` → `Threshold1`) or `<Subsystem><Mode>`.
4. **Polling.** Each attribute's `io_ref` holds its URL and `update_period`: status
   values every 0.2 s, config values once at startup (`ONCE`). fastcs runs the polling.

**Writing a value** (`io.py`, `EigerAttributeIO`): the driver PUTs the new value. The
detector replies with the list of other parameters that may have changed as a result
(e.g. changing the photon energy changes the thresholds). Those are queued on the root
controller, which marks `stale_parameters` until they are refreshed. `bit_depth_image`
and `bit_depth_readout` are refreshed immediately instead of queued.

## The three subsystems

| Subsystem | What it is on the detector | What the controller adds in code |
|---|---|---|
| **detector** (`eiger_detector_controller.py`) | The camera itself: exposure (`count_time`, `frame_time`), number of images and triggers, trigger mode, energy and thresholds, bit depth, compression, geometry, temperature, humidity, state | Commands `initialize`, `arm`, `trigger`, `disarm`, `abort`, `cancel`; attribute `trigger_exposure` for `inte` trigger mode; type hints for the introspected attributes its logic uses (`bit_depth_image`, `compression`, `trigger_mode`) |
| **monitor** (`eiger_monitor_controller.py`) | A low-rate preview image feed for live viewing, not the data path: `mode`, `buffer_size`, `discard_new`; status `state`, `buffer_free`, `dropped` | A `@scan(1)` that fetches the next preview image (TIFF); it only prints it for now (TODO: publish as a waveform) |
| **stream** (`eiger_stream_controller.py`) | The full-rate data output: every frame is streamed over the network (ZeroMQ) to a receiver such as Odin: `mode`, `format`, `header_detail`, appendices; status `state`, `dropped` | Nothing; only the introspected parameters |

## Odin variant

`EigerOdinController` (`controllers/odin/`) is the same root controller plus an `OD`
tree for the Odin file writer. It copies detector settings such as compression and
bit depth to the writer.

## Testing

Unit tests use fake connections (`tests/test_eiger_controller.py` etc.). System tests
(`tests/system/`) run against a tickit-simulated Eiger; `tests/system/parameters.json`
is a recorded list of every parameter per subsystem.

## What this means for fastcs-gatan

- The "ask the device for its parameters" design relies on the Eiger's API describing
  itself. Gatan's binary protocol (SerialEMCCD GatanSocket) does not, so fastcs-gatan
  declares its attributes by hand.
- Reusable ideas: putting device IO in an `AttributeIO` with per-attribute `io_ref`s and
  `update_period`s instead of ad-hoc calls; the update queue with a `stale_parameters`
  flag, and waiting on it before arming or starting an acquisition.
