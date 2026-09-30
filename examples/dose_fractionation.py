"""Take one dose-fractionated exposure through fastcs-gatan's REST interface.

Frames are written by the SerialEMCCD plugin on the DM computer; this script
only gets back the frame count, error code and file path.

The defaults reproduce this working GatanDetectorClient run on the Talos K3:

    python examples/probe_real_server.py --allow-acquire --read-mode k3-counting
        --k2-params --bin-counting --dose-frac --frame-time 0.013316
        --scaling 1.0 --processing gain --width 5760 --height 4092
        --exposure 0.1 --save-frames 'X:\\DoseFractions\\kwd30084'
        --save-format mrc --frame-root fmt_mrc

1. Start the driver:

       python -m fastcs_gatan run Talos_K3.yaml

2. In another terminal:

       python examples/dose_fractionation.py

   --yes skips the confirmation prompt; --id GATAN for gatan.yaml.

Calls sent to the plugin, in order (as GatanDetectorClient does):
    SetCurrentCamera, SetReadMode, SetK2Parameters2, SetupFileSaving2,
    GetAcquiredImage, GetFileSaveResult, then SetK2Parameters2 to switch
    frame saving off again.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8080"
K2_TAKE_BINNED_FRAMES = 1 << 5  # counting frames at physical pixel size


def put(path, value=None):
    """PUT a setting (with value) or trigger a command (without)."""
    data = None if value is None else json.dumps({"value": value}).encode()
    req = urllib.request.Request(f"{BASE}/{path}", data=data, method="PUT")
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req, timeout=10).close()


def get(path):
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=10) as r:
        return json.load(r)["value"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", default="TALOS-K3", help="controller id in the YAML")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--exposure", type=float, default=0.1, help="total seconds")
    ap.add_argument("--frame-time", type=float, default=0.013316,
                    help="seconds per frame (0: use --frames)")
    ap.add_argument("--frames", type=int, default=None,
                    help="number of frames, used when --frame-time is 0")
    ap.add_argument("--save-dir", default=r"X:\DoseFractions\kwd30084",
                    help="folder on the DM computer")
    ap.add_argument("--root", default="fmt_mrc", help="file name root")
    ap.add_argument("--read-mode", type=int, default=4, help="3=K3 linear, 4=K3 counting")
    ap.add_argument("--scaling", type=float, default=1.0)
    ap.add_argument("--no-bin-counting", action="store_true",
                    help="super-resolution counting frames (2x per axis)")
    ap.add_argument("--width", type=int, default=5760)
    ap.add_argument("--height", type=int, default=4092)
    ap.add_argument("--binning", type=int, default=1)
    ap.add_argument("--processing", type=int, default=2,
                    help="0=unprocessed 1=dark-subtracted 2=gain-normalised")
    ap.add_argument("--hardware-proc", type=int, default=0)
    ap.add_argument("--shutter", type=int, default=0, help="0=beam blank")
    ap.add_argument("--save-format-flags", type=int, default=0, help="0=MRC stack")
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = ap.parse_args()

    if args.frame_time > 0:
        frames = max(1, round(args.exposure / args.frame_time))
    elif args.frames:
        frames = args.frames
    else:
        ap.error("give --frame-time or --frames")
    k2_flags = 0 if args.no_bin_counting else K2_TAKE_BINNED_FRAMES

    cam = f"{args.id}/camera"
    acq = f"{args.id}/acquisition"
    settings = {
        f"{cam}/current-camera": args.camera,
        f"{acq}/read-mode": args.read_mode,
        f"{acq}/scaling": args.scaling,
        f"{acq}/hardware-proc": args.hardware_proc,
        f"{acq}/k2-flags": k2_flags,
        f"{acq}/width": args.width,
        f"{acq}/height": args.height,
        f"{acq}/binning": args.binning,
        f"{acq}/processing": args.processing,
        f"{acq}/shutter": args.shutter,
        f"{acq}/save-dir": args.save_dir,
        f"{acq}/save-root-name": args.root,
        f"{acq}/save-format-flags": args.save_format_flags,
        f"{acq}/dose-frac-exposure": args.exposure,
        f"{acq}/dose-frac-frame-time": args.frame_time,
        f"{acq}/dose-frac-num-frames": frames,
    }

    print(f"Dose-fractionated exposure on {args.id} via {BASE}:")
    for path, value in settings.items():
        print(f"  {path.split('/', 1)[1]:32s} {value}")
    print(f"  {'expected frames':32s} {frames}")
    try:
        if get(f"{acq}/dose-frac-busy"):
            print("An exposure is already running; aborting.")
            return 1
    except urllib.error.URLError as exc:
        print(f"Driver not reachable at {BASE}: {exc}")
        return 1
    if not args.yes:
        print("\nThis EXPOSES THE DETECTOR and writes files on the DM computer.")
        if input("Type 'ACQUIRE' to proceed: ").strip() != "ACQUIRE":
            print("Aborted, nothing done.")
            return 0

    try:
        for path, value in settings.items():
            put(path, value)
        put(f"/{cam}/select")              # SetCurrentCamera
        put(f"/{acq}/apply-read-mode")     # SetReadMode
        t0 = time.monotonic()
        put(f"/{acq}/acquire-dose-fractionated")  # commands live under //<id>/...
    except urllib.error.HTTPError as exc:
        # A failed command (e.g. the plugin connection is broken) aborts here,
        # before the exposure is started.
        print(f"\nAborted: {exc.url} returned {exc.code}. See the driver's log.")
        return 1

    print("\nstarted", end="", flush=True)
    while get(f"{acq}/dose-frac-busy"):
        if time.monotonic() - t0 > args.timeout:
            print(f"\nstill busy after {args.timeout} s; check the driver.")
            return 1
        print(".", end="", flush=True)
        time.sleep(0.5)
    print(f" finished after {time.monotonic() - t0:.1f} s\n")

    for label, path in [
        ("state", "dose-frac-state"),
        ("frames saved", "frames-saved"),
        ("save error", "save-error"),
        ("saved path (DM PC)", "saved-path"),
        ("message", "dose-frac-message"),
    ]:
        print(f"  {label:22s} {get(f'{acq}/{path}')}")
    return 0 if get(f"{acq}/dose-frac-state") == "Done" else 1


if __name__ == "__main__":
    sys.exit(main())
