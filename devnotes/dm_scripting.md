# Scripting DigitalMicrograph through the SerialEMCCD plugin

Investigated 2026-10-12 by reading the SerialEMCCD plugin, SerialEM and
GatanDetectorClient sources. Not yet tested on the real system unless stated.
SerialEMCCD is GPL-2: behavior is described here, no code is copied.

## Short answer

You can run a script on the DM computer from a network client, but only as
**DigitalMicrograph's own script language**, sent as text inside the request.
There is no file upload, and the plugin has no Python support.

## The four kinds of scripting

| Scripting | Runs where | Talks to | Reachable from a network client? |
|---|---|---|---|
| **DM script** (DigitalMicrograph's own language) | inside DM | DM and the Gatan hardware | **Yes**, through the plugin |
| **DM Python** (newer GMS versions) | inside DM | DM | Not directly; the plugin has no Python support |
| **SerialEM macros** | inside SerialEM | SerialEM's microscope and camera control | No; unrelated to the plugin |
| **SerialEM Python** | a separate Python process | SerialEM, through a socket server in SerialEM (`SerialEM/PythonServer.cpp`) | Only with SerialEM running; it drives SerialEM, not DM |

## What the plugin supports

Two calls, both taking DM script text only:

- **`ExecuteScript`** (function code 1) runs a script now.
  - The text is sent inside the request.
  - The plugin first stops continuous mode and waits for any acquisition in
    progress, and can prepend lines that select the current camera.
  - It runs the text with DigitalMicrograph's interpreter
    (`DM::ExecuteScriptString`, `SerialEMCCD/TemplatePlugIn.cpp`).
  - **Only one number comes back**: the value the script passes to `Exit(n)`,
    or −999 if the script failed (status 1). No text, files or images.
- **`QueueScript`** (function code 5) stores script text that is run just before
  the **next acquisition**. SerialEM uses this to change something (e.g. an
  energy-filter setting) at the right moment.

Argument layouts are in `SerialEMCCD/SocketPathway.cpp` (argument table and
handlers). No call in the protocol uploads files.

## How SerialEM and GatanDetectorClient use it

- SerialEM's camera code uses `ExecuteScript` for things with no dedicated plugin
  call, such as energy-filter control and reading the sensor size
  (`SerialEM/CameraController.cpp`, `EasyRunScript`). SerialEM's macro language
  has no command for sending your own DM script.
- GatanDetectorClient has `execute_script()` and `queue_script()`
  (`gatan_client/gatan_socket.py`). It found on the real system (GMS 3.6.1,
  plugin version 120) that only one particular script works for reading the
  sensor size (see `gatan_client/live.py`). Its `examples/dm_display.py`, which
  takes and shows an image in DM, is marked as not yet tried on hardware.

## Open questions

- **Getting more than one number back**: a script would have to leave its results
  somewhere, such as a file on the DM computer. Not built or tested.
- **Python on the DM computer**: whether a DM script can hand work to DM's Python,
  or start an external program, depends on DigitalMicrograph's scripting
  functions. Nothing in these sources shows it; check Gatan's documentation or try
  it.

## Cautions

- `ExecuteScript` runs arbitrary code inside DM. It can move hardware or take
  exposures, so it is not a read-only call.
- fastcs-gatan does not implement scripting; it is out of scope.

## Plugin quirk

The plugin's code that records the result of `ExecuteScript`
(`PlugInWrapper::ExecuteScript`, `SerialEMCCD/TemplatePlugIn.cpp`) uses a
condition that is always true. So after **every** script, including successful
ones, `GetLastError` reports error 25 (`CLIENT_SCRIPT_ERROR`). Judge success by the
returned number (−999 means failure), not by `GetLastError`. Found in the source;
not yet seen on the real system.
