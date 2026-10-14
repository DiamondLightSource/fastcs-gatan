"""Take one dose-fractionated exposure through fastcs-gatan's EPICS PVs, using aioca.

The EPICS version of examples/dose_fractionation.py: same defaults (the
parameters of GatanDetectorClient's session_runner.sh step 26) and the same
calls to the plugin in the same order. Frames are written by the SerialEMCCD
plugin on the DM computer; this script only gets back the frame count, error
code and file path.

1. Start the driver with the EPICS CA transport:

       python -m fastcs_gatan run Talos_K3_ca.yaml

2. In another terminal (on the same machine, point the client at it first):

       export EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO
       python examples/dose_fractionation_aioca.py

   --yes skips the confirmation prompt; --prefix GATAN for a config whose
   controller id is GATAN.

Calls sent to the plugin, in order:
    SetCurrentCamera, SetReadMode, SetK2Parameters2, SetupFileSaving2,
    GetAcquiredImage, GetFileSaveResult, then SetK2Parameters2 to switch
    frame saving off again.
"""

import argparse
import asyncio
import sys
import time

from aioca import DBR_CHAR_STR, FORMAT_CTRL, FORMAT_TIME, caget, camonitor, caput

K2_TAKE_BINNED_FRAMES = 1 << 5  # counting frames at physical pixel size
MAJOR_ALARM = 2


async def run_command(pv):
    """Write 1 to a command PV; it goes into MAJOR alarm if the command failed."""
    await caput(pv, 1, wait=True)
    result = await caget(pv, format=FORMAT_TIME)
    if result.severity >= MAJOR_ALARM:
        raise RuntimeError(f"{pv} failed; see the driver's log")


async def main(args):
    if args.frame_time > 0:
        frames = max(1, round(args.exposure / args.frame_time))
    elif args.frames:
        frames = args.frames
    else:
        sys.exit("give --frame-time or --frames")
    k2_flags = 0 if args.no_bin_counting else K2_TAKE_BINNED_FRAMES

    cam = f"{args.prefix}:Camera:"
    acq = f"{args.prefix}:Acquisition:"
    numbers = {
        cam + "CurrentCamera": args.camera,
        acq + "ReadMode": args.read_mode,
        acq + "Scaling": args.scaling,
        acq + "HardwareProc": args.hardware_proc,
        acq + "K2Flags": k2_flags,
        acq + "Width": args.width,
        acq + "Height": args.height,
        acq + "Binning": args.binning,
        acq + "Processing": args.processing,
        acq + "Shutter": args.shutter,
        acq + "SaveFormatFlags": args.save_format_flags,
        acq + "DoseFracExposure": args.exposure,
        acq + "DoseFracFrameTime": args.frame_time,
        acq + "DoseFracNumFrames": frames,
    }
    texts = {  # long-string PVs: written with DBR_CHAR_STR (like caput -S)
        acq + "SaveDir": args.save_dir,
        acq + "SaveRootName": args.root,
    }

    print(f"Dose-fractionated exposure on {args.prefix} over EPICS CA:")
    for pv, value in {**numbers, **texts}.items():
        print(f"  {pv:42s} {value}")
    print(f"  {'expected frames':42s} {frames}")
    try:
        busy = await caget(acq + "DoseFracBusy", timeout=5)
    except Exception as exc:
        print(f"Driver not reachable over EPICS CA: {exc}")
        return 1
    if busy:
        print("An exposure is already running; aborting.")
        return 1
    if not args.yes:
        print("\nThis EXPOSES THE DETECTOR and writes files on the DM computer.")
        if input("Type 'ACQUIRE' to proceed: ").strip() != "ACQUIRE":
            print("Aborted, nothing done.")
            return 0

    # Settings, then the two setup commands. A failed command aborts here,
    # before the exposure is started.
    for pv, value in numbers.items():
        await caput(pv, value, wait=True)
    for pv, value in texts.items():
        await caput(pv, value, datatype=DBR_CHAR_STR, wait=True)
    try:
        await run_command(cam + "Select")  # SetCurrentCamera
        await run_command(acq + "ApplyReadMode")  # SetReadMode
    except RuntimeError as exc:
        print(f"\nAborted: {exc}")
        return 1

    # Watch the state PV, start the exposure, and wait until it reports the end.
    done = asyncio.Event()

    def on_state(value):
        if value.enums[int(value)] in ("DONE", "FAILED"):
            done.set()

    t0 = time.monotonic()
    try:
        await run_command(acq + "AcquireDoseFractionated")
    except RuntimeError as exc:
        print(f"\nAborted: {exc}")
        return 1
    print("\nstarted ...", flush=True)
    # Attached after the start command, so the first update is this exposure's
    # state (ACQUIRING, or already DONE/FAILED), never a previous exposure's.
    monitor = camonitor(acq + "DoseFracState", on_state, format=FORMAT_CTRL)
    try:
        await asyncio.wait_for(done.wait(), timeout=args.timeout)
    except TimeoutError:
        print(f"\nstill busy after {args.timeout} s; check the driver.")
        return 1
    finally:
        monitor.close()
    print(f"finished after {time.monotonic() - t0:.1f} s\n")

    state = await caget(acq + "DoseFracState", format=FORMAT_CTRL)
    print(f"  {'state':22s} {state.enums[int(state)]}")
    print(f"  {'frames saved':22s} {await caget(acq + 'FramesSaved')}")
    print(f"  {'save error':22s} {await caget(acq + 'SaveError')}")
    for label, name in [
        ("saved path (DM PC)", "SavedPath"),
        ("message", "DoseFracMessage"),
    ]:
        print(f"  {label:22s} {await caget(acq + name, datatype=DBR_CHAR_STR)}")
    return 0 if state.enums[int(state)] == "DONE" else 1


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--prefix", default="TALOS-K3", help="controller id in the YAML")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--exposure", type=float, default=0.1, help="total seconds")
    ap.add_argument(
        "--frame-time",
        type=float,
        default=0.013316,
        help="seconds per frame (0: use --frames)",
    )
    ap.add_argument(
        "--frames", type=int, default=None, help="number of frames, if --frame-time 0"
    )
    ap.add_argument(
        "--save-dir", default=r"X:\DoseFractions\kwd30084", help="folder on DM PC"
    )
    ap.add_argument("--root", default="fmt_mrc", help="file name root")
    ap.add_argument("--read-mode", type=int, default=4, help="3=K3 linear, 4=counting")
    ap.add_argument("--scaling", type=float, default=1.0)
    ap.add_argument(
        "--no-bin-counting",
        action="store_true",
        help="super-resolution counting frames (2x per axis)",
    )
    ap.add_argument("--width", type=int, default=5760)
    ap.add_argument("--height", type=int, default=4092)
    ap.add_argument("--binning", type=int, default=1)
    ap.add_argument(
        "--processing",
        type=int,
        default=2,
        help="0=unprocessed 1=dark-subtracted 2=gain-normalised",
    )
    ap.add_argument("--hardware-proc", type=int, default=0)
    ap.add_argument("--shutter", type=int, default=0, help="0=beam blank")
    ap.add_argument("--save-format-flags", type=int, default=0, help="0=MRC stack")
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
