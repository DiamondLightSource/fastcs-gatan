# Architecture

## Design principle: mirror the SerialEMCCD plugin

fastcs-gatan does not talk to the camera or to DigitalMicrograph (DM)
directly. It is a client of the [SerialEMCCD](https://github.com/mastcu/SerialEMCCD)
plugin, which runs inside DM on the camera PC and offers DM's camera
control over a TCP socket (the "GatanSocket" protocol, port 48890). SerialEM
uses the same plugin and protocol.

So the driver is shaped by what the plugin offers. The plugin's interface
(`IDMCamera` in `SerialEMCCD.idl`; the socket calls in `SocketPathway.cpp`)
falls into a few capability areas: version and diagnostics, camera selection
and insertion, read mode and K2/K3 parameters, image acquisition, frame
saving, and a few others. fastcs-gatan has one attribute group per area it
covers, and each attribute is either an argument or a result of a plugin
call, or a small driver-only helper around one. {doc}`../reference/attributes`
lists them all in these groups; {doc}`../reference/plugin-calls` lists the
calls.

## Layers

```{graphviz}
digraph architecture {
    rankdir=TB;
    node [shape=box, fontname="sans-serif", fontsize=10];
    edge [fontname="sans-serif", fontsize=9];

    subgraph cluster_clients {
        label="Clients"; style=dashed;
        epics [label="EPICS CA clients\n(Phoebus, aioca, caget)"];
        rest  [label="REST clients\n(HTTP, port 8080)"];
    }

    subgraph cluster_driver {
        label="fastcs-gatan (this driver)";

        subgraph cluster_transports {
            label="fastcs transports"; style=dotted;
            t_ca   [label="EpicsCATransport"];
            t_rest [label="RestTransport"];
        }

        subgraph cluster_controllers {
            label="Controllers and attribute groups"; style=rounded;
            root   [label="GatanController\nStatus"];
            camera [label="camera: CameraController\n(selection) | Insertion"];
            acq    [label="acquisition: AcquisitionController\nReadMode | Acquire | Continuous | FrameSaving"];
        }

        conn [label="GatanSocketConnection\n(one GS_* request at a time)"];
    }

    subgraph cluster_dm {
        label="DM PC"; style=dashed;
        plugin [label="SerialEMCCD plugin\nGatanSocket server, port 48890"];
        dm     [label="DigitalMicrograph\n+ K3 camera"];
    }

    epics -> t_ca;
    rest  -> t_rest;
    t_ca -> root; t_rest -> root;
    root -> camera; root -> acq;
    root -> conn; camera -> conn; acq -> conn;
    conn -> plugin [label="TCP"];
    plugin -> dm;
}
```

From top to bottom:

- **Transports** (from fastcs) publish every attribute as an EPICS PV and a
  REST endpoint. The YAML config passed to `fastcs-gatan run` chooses which
  transports start.
- **Controllers** hold the attributes and commands. `GatanController` is the
  root; it connects at startup, reads the version and status values, and
  adds two sub-controllers: `camera` and `acquisition`. The group names
  (Status, Insertion, ReadMode, ...) organise the EPICS screens.
- **`GatanSocketConnection`** turns each method call into one plugin call
  over TCP and decodes the reply.
- **The plugin** runs each call in DM: some directly through DM's C++ API,
  some by generating and running a DM script.

## From attribute group to plugin call

```{graphviz}
digraph groups {
    rankdir=LR;
    node [shape=box, fontname="sans-serif", fontsize=10];
    edge [fontname="sans-serif", fontsize=9];

    subgraph cluster_groups {
        label="fastcs-gatan attribute groups";
        status  [label="Status"];
        cam     [label="camera\n+ Insertion"];
        readm   [label="ReadMode"];
        acquire [label="Acquire\n(exposure parameters)"];
        single  [label="single image\n(acquire_image)"];
        cont    [label="Continuous\n(not implemented)"];
        saving  [label="FrameSaving\n(dose fractionation)"];
    }

    subgraph cluster_calls {
        label="SerialEMCCD plugin calls";
        c_ver   [label="GetDMVersion\nGetPluginVersion\nGetLastError\nGetLastDoseRate"];
        c_cam   [label="GetNumberOfCameras\nSetCurrentCamera\nIsCameraInserted\nInsertCamera"];
        c_k2    [label="SetReadMode\nSetK2Parameters2"];
        c_acq   [label="GetAcquiredImage", style=bold];
        c_stop  [label="StopContinuousCamera"];
        c_save  [label="SetupFileSaving2\nGetFileSaveResult"];
    }

    status -> c_ver;
    cam -> c_cam;
    readm -> c_k2;
    acquire -> c_acq [style=dashed, label="arguments"];
    single -> c_acq;
    cont -> c_acq; cont -> c_stop;
    saving -> c_k2; saving -> c_save; saving -> c_acq;
}
```

`GetAcquiredImage` is the plugin's one acquisition call. Single images,
continuous acquisition and dose fractionation all go through it; what it
does depends on its `processing` argument and on the frame-saving state set
by `SetK2Parameters2` before it (see {doc}`../reference/attributes`,
"Exposure parameters"). The parameters it shares between the three modes
(size, exposure, binning, processing, shutter) are in group Acquire.

Plugin areas fastcs-gatan does not cover: DM scripting, dark/gain
references and defect lists, frame alignment, DigiScan/STEM, and the
shutter and settling calls (implemented on the connection, but with no
attributes yet).

## Driver-only attributes

Some attributes have no plugin counterpart. They make the plugin calls
usable from EPICS and REST:

- **Insertion polling:** `insertion_timeout`, `insertion_poll_period`.
  Moving the camera takes about 10 s, so `insert` and `retract` poll
  `IsCameraInserted` until the state changes or the timeout runs out.
- **Dose-fractionation status:** `dose_frac_state`, `dose_frac_busy`,
  `dose_frac_message`. A dose-fractionated exposure runs in the background,
  so clients need a way to see it finish; `saved_path` is worked out from
  the saving settings, following the plugin's file naming.
- **Dose-fractionation inputs:** `dose_frac_num_frames`,
  `dose_frac_exposure`, `dose_frac_frame_time`. The driver turns them into
  the plugin's exposure time and frame time.
- **Local saving of single images:** `local_save_dir`, `local_save_root`,
  `local_saved_path` write each single image as an MRC file on the driver's
  machine.

## Connection and threading

- **One client at a time.** The plugin serves one socket client: when a new
  client connects, it closes the existing one
  ([`SocketPathway.cpp` lines 350-359](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L350-L359)).
  Never run fastcs-gatan against a plugin that SerialEM is using.
- **One call at a time.** The connection sends one request and waits for its
  reply. Multi-call sequences (dose fractionation) hold the connection with
  `exclusive()` so nothing can interleave; a call from another thread while
  it is held fails straight away with "connection busy" rather than
  waiting.
- **Blocking calls.** `acquire_image` runs on the driver's event loop and
  blocks it until the image has arrived, so other attributes don't update
  during a single exposure and its transfer. The dose-fractionation sequence
  runs in a worker thread instead and reports progress through its status
  attributes.
- **Fail fast.** A broken connection is not retried: the call fails, the
  connection is closed, and the driver needs restarting.

## Sources

- **Plugin behaviour**: the SerialEMCCD source, cited by file and line at
  commit [`4d6e4b1`](https://github.com/mastcu/SerialEMCCD/tree/4d6e4b1)
  (plugin version 121). SerialEMCCD is GPL-2; fastcs-gatan is Apache-2.0,
  so its code is only cited and its behaviour described, never copied.
- **Wire format and call arguments**: SerialEM's MIT-licensed
  `GatanSocket.cpp`, `BaseSocket.cpp` and `SEMCCDDefines.h`, checked against
  the plugin's argument table in `SocketPathway.cpp`. The connection code was
  ported from GatanDetectorClient's `gatan_socket.py` (Apache-2.0; see the
  `NOTICE` file), but fastcs-gatan does not depend on GatanDetectorClient.
