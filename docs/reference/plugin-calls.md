# SerialEMCCD plugin calls

Every `GS_*` call fastcs-gatan makes, in the same groups as
{doc}`attributes`. Codes are from `SEMCCDDefines.h`; argument counts match
the plugin's argument table
([`SocketPathway.cpp` L79-L120](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L79-L120),
commit `4d6e4b1`), and the function code itself is not counted.
`GatanSocketConnection` methods are in `fastcs_gatan.connection`.

## Message format

- **Request:** a 4-byte length (whole message, in bytes), then the
  arguments grouped by type: the function code and other longs (int32),
  then BOOLs (int32), then doubles (float64), then an optional array of
  longs (used to carry strings).
- **Reply:** the same layout. The first long is the status: 0 = OK,
  otherwise an error code (`SEMCCD_ERRORS`).
- **Image reply:** five longs (status, array size, width, height, number of
  chunks), then the pixel data, 2 bytes per pixel, in chunks of up to
  32 MiB. Before each chunk after the first, the client sends a bare
  `GS_ChunkHandshake` (code 24)
  ([L849-L878](https://github.com/mastcu/SerialEMCCD/blob/4d6e4b1/SocketPathway.cpp#L849-L878)).

## Version and diagnostics

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `GetDMVersion` | 14 | `get_dm_version()` | | long version | `dm_version` |
| `GetDMVersionAndBuild` | 42 | `get_dm_version_and_build()` | | longs version, build | not exposed |
| `GetPluginVersion` | 31 | `get_plugin_version()` | | long version | `plugin_version` |
| `GetLastError` | 32 | `get_last_error()` | | long error | `last_error` |
| `GetDMCapabilities` | 15 | `get_dm_capabilities()` | | BOOLs can select shutter, can set settling, open shutter works | not exposed |

## Dose rate

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `GetLastDoseRate` | 40 | `get_last_dose_rate()` | | double dose rate | `last_dose_rate` |

## Camera selection and insertion

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `GetNumberOfCameras` | 11 | `get_number_of_cameras()` | | long count | `num_cameras` |
| `SetCurrentCamera` | 4 | `set_current_camera(camera)` | long camera | | `select` |
| `SelectCamera` | 9 | `select_camera(camera)` | long camera | | not used |
| `IsCameraInserted` | 12 | `is_camera_inserted(camera)` | long camera | BOOL inserted | `inserted` |
| `InsertCamera` | 13 | `insert_camera(camera, state)` | long camera; BOOL state | | `insert`, `retract` |

## Shutter and settling

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `SetShutterNormallyClosed` | 16 | `set_shutter_normally_closed(camera, shutter)` | longs camera, shutter | | not used |
| `SetNoDMSettling` | 17 | `set_no_dm_settling(camera)` | long camera | | not used |

## Read mode and K2/K3 parameters

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `SetReadMode` | 10 | `set_read_mode(mode, scaling)` | long mode; double scaling | | `apply_read_mode` |
| `SetK2Parameters2` | 29 | `set_k2_parameters2(...)` | longs mode, hardwareProc, rotationFlip, flags, filter size; BOOLs doseFrac, alignFrames, saveFrames; doubles scaling, frameTime and 4 more (sent as 0); array: filter name | | `apply_k2_parameters`, `acquire_dose_fractionated` |

## Exposure: `GetAcquiredImage`

Shared by single image, continuous and dose fractionation; see
{doc}`attributes` for what decides the mode. Every call returns one image.

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `GetAcquiredImage` | 6 | `get_acquired_image(...)` | longs array size, width, height, processing, binning, top, left, bottom, right, shutter, shutter delay, divide-by-2, corrections; doubles exposure, settling | image reply: width, height, pixels | `acquire_image`, `acquire_dose_fractionated` |

fastcs-gatan sends top and left as 0, bottom and right as the height and
width, and shutter delay, divide-by-2, corrections and settling as 0.

## Continuous

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `GetAcquiredImage` with the continuous bits in processing | 6 | | as above | as above | `start_continuous` (not implemented) |
| `StopContinuousCamera` | 30 | `stop_continuous_camera()` (not implemented) | | | `stop_continuous` |

## Dose fractionation (frame saving)

| Call | Code | Method | Sends | Returns | Used by |
|---|---|---|---|---|---|
| `SetupFileSaving2` | 27 | `setup_file_saving2(...)` | longs rotationFlip, flags, names size; BOOL filePerImage; doubles pixelSize and 4 more (sent as 0); array: save folder, root name, then any strings the flags call for | long error | `acquire_dose_fractionated` |
| `GetFileSaveResult` | 26 | `get_file_save_result()` | | longs frames saved, error | `frames_saved`, `save_error` |

Plus `SetK2Parameters2` and `GetAcquiredImage` from the groups above.
