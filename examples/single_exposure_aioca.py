"""Take one single exposure through fastcs-gatan's EPICS PVs, using aioca, and
save the transferred frame as an MRC file on the driver's machine.

Defaults are the parameters of GatanDetectorClient's session_runner.sh step 6,
the first frame that worked on the real K3: K3 linear, scaling 0.25,
gain-normalised, 1024 x 1024, 0.1 s, beam-blanked, with SetK2Parameters2
(no dose fractionation, no frame saving on the DM PC).

1. Start the driver with the EPICS CA transport:

       python -m fastcs_gatan run Talos_K3_ca.yaml

2. In another terminal (on the same machine, point the client at it first):

       export EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO
       python examples/single_exposure_aioca.py

   --yes skips the confirmation prompt; --prefix GATAN for a config whose
   controller id is GATAN.

The frame is written by the driver, not this script, to
<save-dir>/<root>_NNNN.mrc (never overwriting); --save-dir is made absolute
here, since a relative path would be resolved in the driver's working directory.

Calls sent to the plugin, in order:
    SetCurrentCamera, SetReadMode, SetK2Parameters2, GetAcquiredImage
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from aioca import DBR_CHAR_STR, FORMAT_TIME, caget, caput

MAJOR_ALARM = 2


async def run_command(pv, timeout=5.0):
    """Write 1 to a command PV and wait for the command to finish; the PV goes
    into MAJOR alarm if the command failed."""
    await caput(pv, 1, wait=True, timeout=timeout)
    result = await caget(pv, format=FORMAT_TIME)
    if result.severity >= MAJOR_ALARM:
        raise RuntimeError(f"{pv} failed; see the driver's log")


async def main(args):
    save_dir = str(Path(args.save_dir).resolve())
    cam = f"{args.prefix}:Camera:"
    acq = f"{args.prefix}:Acquisition:"
    numbers = {
        cam + "CurrentCamera": args.camera,
        # SetReadMode / SetK2Parameters2
        acq + "ReadMode": args.read_mode,
        acq + "Scaling": args.scaling,
        acq + "HardwareProc": args.hardware_proc,
        acq + "DoseFrac": 0,
        acq + "FrameTime": args.frame_time,
        acq + "AlignFrames": 0,
        acq + "SaveFrames": 0,
        acq + "RotationFlip": 0,
        acq + "K2Flags": 0,
        # GetAcquiredImage
        acq + "Width": args.width,
        acq + "Height": args.height,
        acq + "Binning": args.binning,
        acq + "Processing": args.processing,
        acq + "Shutter": args.shutter,
        acq + "Exposure": args.exposure,
    }
    texts = {  # long-string PVs: written with DBR_CHAR_STR (like caput -S)
        acq + "LocalSaveDir": save_dir,
        acq + "LocalSaveRoot": args.root,
    }

    print(f"Single exposure on {args.prefix} over EPICS CA:")
    for pv, value in {**numbers, **texts}.items():
        print(f"  {pv:42s} {value}")
    try:
        busy = await caget(acq + "DoseFracBusy", timeout=5)
    except Exception as exc:
        print(f"Driver not reachable over EPICS CA: {exc}")
        return 1
    if busy:
        print("A dose-fractionated exposure is running; aborting.")
        return 1
    if not args.yes:
        print("\nThis EXPOSES THE DETECTOR.")
        if input("Type 'ACQUIRE' to proceed: ").strip() != "ACQUIRE":
            print("Aborted, nothing done.")
            return 0

    for pv, value in numbers.items():
        await caput(pv, value, wait=True)
    for pv, value in texts.items():
        await caput(pv, value, datatype=DBR_CHAR_STR, wait=True)
    try:
        await run_command(cam + "Select")  # SetCurrentCamera
        await run_command(acq + "ApplyReadMode")  # SetReadMode
        await run_command(acq + "ApplyK2Parameters")  # SetK2Parameters2
    except RuntimeError as exc:
        print(f"\nAborted before the exposure: {exc}")
        return 1

    # Blocking: the put completes once the frame is transferred and saved.
    previous = await caget(acq + "LocalSavedPath", datatype=DBR_CHAR_STR)
    print("\nacquiring ...", flush=True)
    t0 = time.monotonic()
    try:
        await run_command(acq + "AcquireImage", timeout=args.timeout)
        ok = True
    except RuntimeError as exc:
        print(f"  {exc}")
        ok = False
    print(f"finished after {time.monotonic() - t0:.1f} s\n")

    saved = await caget(acq + "LocalSavedPath", datatype=DBR_CHAR_STR)
    if saved and saved != previous:
        print(f"  {'saved (this machine)':22s} {saved}")
    else:
        print("  no new file saved")
        ok = False
    return 0 if ok else 1


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--prefix", default="TALOS-K3", help="controller id in the YAML")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--exposure", type=float, default=0.1, help="seconds")
    ap.add_argument("--read-mode", type=int, default=3, help="3=K3 linear, 4=counting")
    ap.add_argument("--scaling", type=float, default=0.25)
    ap.add_argument("--hardware-proc", type=int, default=0)
    ap.add_argument(
        "--frame-time",
        type=float,
        default=0.025,
        help="sent with SetK2Parameters2; unused without dose fractionation",
    )
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--binning", type=int, default=1)
    ap.add_argument(
        "--processing",
        type=int,
        default=2,
        help="0=unprocessed 1=dark-subtracted 2=gain-normalised",
    )
    ap.add_argument("--shutter", type=int, default=0, help="0=beam blank")
    ap.add_argument(
        "--save-dir", default="frames", help="folder on the driver's machine"
    )
    ap.add_argument("--root", default="single", help="file name root")
    ap.add_argument(
        "--timeout", type=float, default=120, help="seconds to wait for the frame"
    )
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
