# Example 1: A dose-fractionated exposure over REST and EPICS

Frames are saved on the DigitalMicrograph (DM) PC; the driver only gets back a summed
image and a saved-frame count. Runs without hardware against GatanDetectorClient's
mock server.

## fastcs in brief

A fastcs driver is a tree of controllers (`GATAN` → `camera`, `acquisition`), each
with **attributes** (read-only `AttrR`, writable `AttrRW`) and **commands**
(`@command` methods). The **transports** in the YAML config (REST, EPICS, ...) expose
that tree over their protocol; the driver code is the same for all of them.

## The feature (all in `acquisition`)

| Step | Use |
|---|---|
| Set up | `read_mode`, `width`, `height`, `save_dir` (folder on the DM PC), `save_root_name`, `dose_frac_num_frames`, `dose_frac_exposure` (total seconds) |
| Start | command `acquire_dose_fractionated` (returns at once) |
| Wait | `dose_frac_busy`, `dose_frac_state` (Idle / Acquiring / Done / Failed) |
| Results | `frames_saved`, `save_error`, `saved_path` (`<save_dir>\<root>.mrc`), `dose_frac_message` |

## Setup

```bash
# 1. mock server (VS Code: "Gatan: mock server (K3)")
cd /workspaces/GatanDetectorClient-0.1.0 && python -m gatan_client.mock_server --k3 --port 48890
# 2. driver (VS Code: "Gatan: run")
cd /workspaces/fastcs-gatan && python -m fastcs_gatan run gatan.yaml
```

`gatan.yaml` serves REST on port 8080; add `- epicsca: {}` under `transport:` for
EPICS. With the mock, use read mode 3 (K3 linear): counting mode only accepts the
full sensor size.

## REST

```bash
B=localhost:8080/GATAN/acquisition
curl -X PUT -H 'Content-Type: application/json' -d '{"value": 20}' $B/dose-frac-num-frames
curl -X PUT -H 'Content-Type: application/json' -d '{"value": "/tmp/frames"}' $B/save-dir
curl -X PUT localhost:8080//GATAN/acquisition/acquire-dose-fractionated   # start
curl $B/dose-frac-busy       # {"value":false} when done
curl $B/saved-path
```

All endpoints are listed at `http://localhost:8080/docs`.

## EPICS

PV name = `<id>:<SubController>:<Attribute>` in PascalCase, e.g.
`GATAN:Acquisition:DoseFracNumFrames`. Settings have a `_RBV` readback PV; commands
are PVs you write `1` to; text PVs need `-S`.

```bash
P=GATAN:Acquisition
caput    $P:DoseFracNumFrames 20
caput -S $P:SaveDir /tmp/frames
caput    $P:AcquireDoseFractionated 1   # start
caget    $P:DoseFracBusy                # 0 when done
caget -S $P:SavedPath
```

Without the EPICS tools, the Python library `aioca` (`caget`/`caput`, with
`datatype=DBR_CHAR_STR` for text) does the same.

## Compared

| | REST | EPICS |
|---|---|---|
| Name | `/GATAN/acquisition/dose-frac-num-frames` | `GATAN:Acquisition:DoseFracNumFrames` |
| Read back a setting | `GET` the same URL | `..._RBV` PV |
| Command | `PUT` to `//GATAN/...` | write `1` to the PV |
| Command error | HTTP error | MAJOR alarm on the command PV |
| `dose_frac_state` | `"Done"` | `DONE` |
| Change notifications | poll | `camonitor` |

Note: EPICS limits attribute descriptions to 40 characters (the driver won't start
otherwise); a test in `tests/test_gatan_controller.py` checks this.
