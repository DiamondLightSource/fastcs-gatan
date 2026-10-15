# Attributes

Attributes and commands grouped by the SerialEMCCD plugin capability they
belong to. Plugin source references are to
[SerialEMCCD at commit `4d6e4b1`](https://github.com/mastcu/SerialEMCCD/tree/4d6e4b1);
the calls themselves are listed in {doc}`plugin-calls`.

## Names

| | EPICS (CA) | REST |
|---|---|---|
| Attribute | `<id>:<SubController>:<Name>`, e.g. `GATAN:Acquisition:DoseFracBusy` | `/<id>/<sub-controller>/<name>`, e.g. `/GATAN/acquisition/dose-frac-busy` |
| Root attribute | `<id>:<Name>`, e.g. `GATAN:DmVersion` | `/<id>/<name>`, e.g. `/GATAN/dm-version` |
| Read-write | setpoint PV, plus `_RBV` readback | `PUT {"value": ...}`, `GET` to read |
| Command | write `1` to the PV; failure gives a MAJOR alarm | `PUT` to `//<id>/...` (double slash) |

`<id>` is the controller id in the YAML config. The PV column in the
tables below leaves out the `<id>:` prefix.

The sections follow the plugin's capability areas. The attribute groups in
the code (which organise the EPICS screens) don't always match them; each
section names the code's sub-controller and group.

The "Plugin side" column says whether an attribute is an *argument* or a
*result* of a plugin call, or *driver* if it exists only in fastcs-gatan.

## Version and diagnostics

Root controller, group Status. Read once when the driver starts; not polled.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `dm_version` | `DmVersion` | Int, R | result of `GetDMVersion` | DM version number |
| `plugin_version` | `PluginVersion` | Int, R | result of `GetPluginVersion` | Plugin API version (`SEMCCD_PLUGIN_VERSION`) |
| `last_error` | `LastError` | Int, R | result of `GetLastError` | Result code of the plugin's last call ([`SocketPathway.cpp` L739-L742](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L739-L742)); 0 = OK, names in `SEMCCD_ERRORS` |

Also implemented on the connection, but not attributes: `GetDMVersionAndBuild`,
`GetDMCapabilities`.

## Dose rate

Root controller, group Status. A section of its own because the plugin
has no area it obviously belongs to.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `last_dose_rate` | `LastDoseRate` | Float, R | result of `GetLastDoseRate` | Dose rate DM reported for the last image, per unbinned pixel per second; 0 if DM couldn't give one ([`TemplatePlugIn.cpp` L3997-L4011](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L3997-L4011)). Read once at startup only, so it does not follow later exposures |

## Camera selection and insertion

`camera` sub-controller: `num_cameras`, `current_camera` and `select` have
no group, the rest are in group Insertion. `current_camera` is the camera
index every call here uses.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `num_cameras` | `Camera:NumCameras` | Int, R | result of `GetNumberOfCameras` | Read at startup |
| `current_camera` | `Camera:CurrentCamera` | Int ≥ 0, RW, default 0 | argument of the calls below | Only sent to the plugin by `select`, `insert`, `retract` and the `inserted` read |
| `select` | `Camera:Select` | command | `SetCurrentCamera(current_camera)` | The plugin stores the index and uses it when it builds DM scripts for later calls ([L504](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L504)). `SelectCamera`, which also runs DM's camera-selection script straight away ([L5914](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L5914)), is on the connection but not used |
| `inserted` | `Camera:Inserted` | Bool, R | result of `IsCameraInserted(current_camera)` | Read at startup and while `insert`/`retract` wait. Runs a DM script ([L6754](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L6754)) |
| `insert` | `Camera:Insert` | command | `InsertCamera(current_camera, true)` | Moves real hardware; then polls `inserted` |
| `retract` | `Camera:Retract` | command | `InsertCamera(current_camera, false)` | As `insert` |
| `insertion_timeout` | `Camera:InsertionTimeout` | Int ≥ 1, RW, default 30 | driver | Seconds `insert`/`retract` wait before failing |
| `insertion_poll_period` | `Camera:InsertionPollPeriod` | Int ≥ 1, RW, default 1 | driver | Seconds between `inserted` reads while waiting |

## Read mode and K2/K3 parameters

`acquisition` sub-controller, group ReadMode. These values are stored in the
driver and only reach the plugin when a command sends them.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `read_mode` | `Acquisition:ReadMode` | Int, RW, default 0 | argument `mode` of `SetReadMode` and `SetK2Parameters2` | 0 K2 linear, 1 K2 counting, 2 K2 super-resolution, 3 K3 linear, 4 K3 counting; above 4 is treated as 4. The plugin treats `mode > 2` as a K3, so a K3 needs 3 or 4. Negative = not a direct detector, which turns dose fractionation and frame saving off ([L5928-L5960](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L5928-L5960)) |
| `scaling` | `Acquisition:Scaling` | Float, RW, default 1.0 | argument `scaling` of the same calls | Count scaling. In K3 linear mode it also carries the per-frame offset |
| `hardware_proc` | `Acquisition:HardwareProc` | Int, RW, default 0 | argument `hardwareProc` of `SetK2Parameters2` | Hardware correction setting, 0, 2, 4 or 6; the plugin clamps it to 0-6 and maps it onto DM's hardware corrections ([L5979-L5980](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L5979-L5980), [L1281](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L1281)) |
| `align_frames` | `Acquisition:AlignFrames` | Bool, RW, default off | argument `alignFrames` of `SetK2Parameters2` | DM frame alignment: out of scope, keep off |
| `rotation_flip` | `Acquisition:RotationFlip` | Int, RW, default 0 | argument `rotationFlip` of `SetK2Parameters2` and `SetupFileSaving2` | Rotation/flip code for saved frames; negative leaves the plugin's value unchanged |
| `k2_flags` | `Acquisition:K2Flags` | Int, RW, default 0 | argument `flags` of `SetK2Parameters2` | Flag bits; 32 (`K2_TAKE_BINNED_FRAMES`) takes K3 frames binned to physical pixels |
| `apply_read_mode` | `Acquisition:ApplyReadMode` | command | `SetReadMode(read_mode, scaling)` | |
| `apply_k2_parameters` | `Acquisition:ApplyK2Parameters` | command | `SetK2Parameters2(...)` with the values above and the three below | The plugin calls `SetReadMode` itself first ([L5978](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L5978)), so this is enough on its own |

Three more `SetK2Parameters2` arguments sit in group FrameSaving in the code.
Only `apply_k2_parameters` reads them; `acquire_dose_fractionated` sends its
own values:

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `dose_frac` | `Acquisition:DoseFrac` | Bool, RW, default off | argument `doseFrac` | |
| `frame_time` | `Acquisition:FrameTime` | Float ≥ 0, RW, default 0.05 | argument `frameTime` | Seconds per sub-frame |
| `save_frames` | `Acquisition:SaveFrames` | Bool, RW, default off | argument `saveFrames` | |

## Exposure parameters (`GetAcquiredImage` arguments)

`GetAcquiredImage` is the plugin's one acquisition call; single images,
continuous acquisition and dose fractionation all use it. What one call does
is decided in `TemplatePlugIn::GetImage`
([L878](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L878)):
frame saving is on only if `SetK2Parameters2` turned on both dose
fractionation and frame saving and `SetupFileSaving2` gave a folder and a
name ([L897-L899](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L897-L899));
continuous mode needs `processing` above 7 and frame saving and alignment
off ([L972-L988](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L972-L988)).

In the code, the parameters below are in `acquisition`, group Acquire, along
with the single-image attributes.

| Mode | Set up by | What the plugin does | Sent to fastcs-gatan |
|---|---|---|---|
| Single image | `processing` 0-7, frame saving off | One exposure; stops continuous mode first if it is running | One image per call |
| Continuous | `processing` > 7 (continuous bits), frame saving and alignment off | First call starts an acquisition loop in a plugin thread; each later call copies out its newest frame ([`GetContinuousFrame`, L3587](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/TemplatePlugIn.cpp#L3587)); `StopContinuousCamera` ends it | One image per call; frames the loop takes between calls never leave the DM PC |
| Dose fractionation | `SetK2Parameters2` (dose fractionation and frame saving on) and `SetupFileSaving2` first | One exposure split into sub-frames, written to disk on the DM PC | One image: the sum. The sub-frames are never sent |

**Every call transfers one full image over the network**, and that is the
slow part. The plugin sends 2 bytes per pixel in chunks of up to 32 MiB,
waiting for a handshake from the client after each one
([`SocketPathway.cpp` L37](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L37),
[L849-L878](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L849-L878)).
A K3 frame at physical pixel size (5760 × 4092) is 47 MB, two chunks: at
least 0.4 s at 1 Gbit/s, before any processing time. A super-resolution
frame would be four times that.

What `GetAcquiredImage` can do on the plugin side, briefly (✓ = used by
fastcs-gatan):

- ✓ exposure time, binning, processing (unprocessed, dark-subtracted,
  gain-normalised), readout area
- ✓ shutter selection; shutter delay, settling time, divide-by-2 and DM
  correction flags (sent as 0)
- continuous mode with a quality setting (planned)
- ✓ dose fractionation with frames saved as MRC, MRCS or TIFF (LZW or ZIP)
  on the DM PC; further options such as 4-bit packing, summing frames
  before saving and a gain-normalised sum, set through flag bits
- early return (send the sum back before saving finishes), deferred sums,
  frame alignment in the plugin, tilt sums: out of scope

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `width` | `Acquisition:Width` | Int ≥ 1, RW, default 1024 | arguments `width`, `right` (and the array size) | Image width in binned pixels; the readout area starts at 0, 0 |
| `height` | `Acquisition:Height` | Int ≥ 1, RW, default 1024 | arguments `height`, `bottom` | Image height in binned pixels |
| `exposure` | `Acquisition:Exposure` | Float ≥ 0, RW, default 0.1 | argument `exposure` | Seconds. Single image and continuous; dose fractionation uses `dose_frac_exposure` |
| `binning` | `Acquisition:Binning` | Int ≥ 1, RW, default 1 | argument `binning` | |
| `processing` | `Acquisition:Processing` | Int, RW, default 0 | argument `processing` | 0 unprocessed, 1 dark-subtracted, 2 gain-normalised. Continuous mode will add its bits on top |
| `shutter` | `Acquisition:Shutter` | Int, RW, default 0 | argument `shutter` | DM shutter index |
| `last_frame` | `Acquisition:LastFrame` | Waveform, R | result: the image | The image from the last call, single or dose-fractionated sum. Up to 4096 × 5760; decoded as unsigned 16-bit (signed/unsigned not settled yet) |

## Single image

`acquisition`, group Acquire.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `acquire_image` | `Acquisition:AcquireImage` | command | `GetAcquiredImage` with the exposure parameters | Returns when the image has arrived. Uses whatever read mode and K2/K3 parameters the plugin last received |
| `local_save_dir` | `Acquisition:LocalSaveDir` | String, RW, default empty | driver | If set, each image is also saved here, on the driver's machine |
| `local_save_root` | `Acquisition:LocalSaveRoot` | String, RW, default `frame` | driver | File names are `<root>_NNNN.mrc`; existing files are never overwritten |
| `local_saved_path` | `Acquisition:LocalSavedPath` | String, R | driver | MRC file of the last saved image |

## Continuous

`acquisition`, group Continuous. Not implemented yet: both commands
currently fail.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `continuous_quality` | `Acquisition:ContinuousQuality` | Int 0-7, RW, default 0 | bits 3-5 of `processing` | |
| `continuous_active` | `Acquisition:ContinuousActive` | Bool, R | driver | |
| `start_continuous` | `Acquisition:StartContinuous` | command | `GetAcquiredImage` with the continuous bits, repeatedly | Each frame fetched is a full image transfer |
| `stop_continuous` | `Acquisition:StopContinuous` | command | `StopContinuousCamera` | |

## Dose fractionation (frames saved on the DM PC)

`acquisition`, group FrameSaving.

`acquire_dose_fractionated` runs, in a worker thread, with nothing else
allowed on the connection in between:

1. `SetK2Parameters2` with dose fractionation and frame saving on, the frame
   time, and frame alignment off
2. `SetupFileSaving2` with the folder, name, pixel size and flags (one stack
   file, not one file per frame)
3. `GetAcquiredImage`: the exposure; the plugin saves the sub-frames and
   returns their sum
4. `GetFileSaveResult`: frames saved and saving error
5. `SetK2Parameters2` with dose fractionation and frame saving off again

Read mode, scaling, hardware processing, rotation/flip and `k2_flags` come
from group ReadMode; size, binning, processing and shutter from the exposure
parameters.

| Attribute | PV | Type | Plugin side | Notes |
|---|---|---|---|---|
| `dose_frac_num_frames` | `Acquisition:DoseFracNumFrames` | Int ≥ 1, RW, default 40 | driver input | Number of sub-frames |
| `dose_frac_exposure` | `Acquisition:DoseFracExposure` | Float ≥ 0, RW, default 2.0 | argument `exposure` of `GetAcquiredImage` | Total exposure in seconds |
| `dose_frac_frame_time` | `Acquisition:DoseFracFrameTime` | Float ≥ 0, RW, default 0 | argument `frameTime` of `SetK2Parameters2` | Seconds per sub-frame; 0 = exposure / frames. The camera may not reach the requested time, so check `frames_saved` |
| `save_dir` | `Acquisition:SaveDir` | String, RW, default empty | in the name strings of `SetupFileSaving2` | Folder **on the DM PC**. Required |
| `save_root_name` | `Acquisition:SaveRootName` | String, RW, default `gatan` | in the name strings of `SetupFileSaving2` | File name without extension |
| `save_pixel_size` | `Acquisition:SavePixelSize` | Float ≥ 0, RW, default 1.0 | argument `pixelSize` of `SetupFileSaving2` | |
| `save_format_flags` | `Acquisition:SaveFormatFlags` | Int, RW, default 0 | argument `flags` of `SetupFileSaving2` | 0 = uncompressed MRC; 8 LZW TIFF, 16 ZIP TIFF, 65536 `.mrcs` extension |
| `acquire_dose_fractionated` | `Acquisition:AcquireDoseFractionated` | command | the sequence above | Returns straight away; watch `dose_frac_busy` |
| `dose_frac_busy` | `Acquisition:DoseFracBusy` | Bool, R | driver | True until the sequence ends |
| `dose_frac_state` | `Acquisition:DoseFracState` | Enum, R | driver | Idle, Acquiring, Done or Failed |
| `dose_frac_message` | `Acquisition:DoseFracMessage` | String, R | driver | Error text, or a note when fewer frames were saved than requested |
| `frames_saved` | `Acquisition:FramesSaved` | Int, R | result `numSaved` of `GetFileSaveResult` | |
| `save_error` | `Acquisition:SaveError` | Int, R | result `error` of `GetFileSaveResult` | 0 = OK, names in `SEMCCD_ERRORS` |
| `saved_path` | `Acquisition:SavedPath` | String, R | driver | Where the plugin wrote the frames, on the DM PC: `<save_dir>\<root>.mrc`, `.mrcs` or `.tif` |

## Shutter and settling

`SetShutterNormallyClosed` and `SetNoDMSettling` are implemented on the
connection but have no attributes yet.

## Not covered

Plugin capabilities fastcs-gatan does not use:

- **DM scripting**: `ExecuteScript`, `QueueScript`
- **Dark and gain references, defects**: `GetDarkReference`,
  `GetGainReference`, `FreeK2GainReference`, `GetDefectList`
- **Frame alignment in the plugin**: `SetupFrameAligning`,
  `FrameAlignResults`, `MakeAlignComFile`, `IsGpuAvailable`,
  `ReturnDeferredSum`, `GetTiltSumProperties`, `SaveFrameMdoc`
- **DigiScan/STEM**: `GetDSProperties`, `AcquireDSImage`, `ReturnDSChannel`,
  `StopDSAcquisition`
- **Other**: `WaitUntilReady`, `SetDMVersion`, `SetDebugMode`

## Known limitations

As the code stands:

- **Continuous acquisition** is not implemented; its commands fail.
- **Group names differ from the plugin areas**: `dose_frac`, `frame_time`
  and `save_frames` are `SetK2Parameters2` arguments but sit in group
  FrameSaving, not ReadMode; group Acquire holds both the shared exposure
  parameters and the single-image attributes.
- **`last_dose_rate`** and the other Status values are read only at startup.
- **`last_frame`** is decoded as unsigned 16-bit; whether the plugin's data
  should be read as signed or unsigned is not settled. Frames larger than
  4096 × 5760 (super-resolution) don't fit it.
- **`acquire_image` blocks the driver** until the image has arrived, so
  nothing else updates meanwhile.
- **Shutter and settling** calls have no attributes, and the shutter delay,
  settling, divide-by-2 and corrections arguments of `GetAcquiredImage` are
  always 0.
- **Plugin version**: the source cited here is plugin version 121; check
  `plugin_version` on the real system, which may run an older plugin.
