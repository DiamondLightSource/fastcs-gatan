"""Write one transferred frame to a single-image MRC file, on the driver's host.

The pixel bytes from the socket are written unchanged after a 1024-byte MRC2014
header; nothing is decoded or converted. The header says MODE 1 (16-bit
signed), as GatanDetectorClient's ``save_mrc`` does for these frames — whether
the plugin's 16 bits are really signed is still open (see the
``_update_last_frame`` TODO in the acquisition controller), and a reader can
reinterpret them as unsigned without touching the file.

Header layout follows the MRC2014 specification (https://www.ccpem.ac.uk/mrc_format/mrc2014.php).
DMIN/DMAX/DMEAN/RMS are left as "not computed" (DMAX < DMIN, RMS < 0), so no
pass over the data is needed.
"""

from __future__ import annotations

import struct
from pathlib import Path

HEADER_BYTES = 1024
MODE_INT16 = 1


def mrc_header(width: int, height: int, labels: list[str] | None = None) -> bytes:
    """MRC2014 header for one ``width`` x ``height`` 16-bit image."""
    hdr = bytearray(HEADER_BYTES)
    struct.pack_into("<3i", hdr, 0, width, height, 1)  # NX, NY, NZ
    struct.pack_into("<i", hdr, 12, MODE_INT16)  # MODE
    struct.pack_into("<3i", hdr, 28, width, height, 1)  # MX, MY, MZ
    struct.pack_into("<3f", hdr, 40, float(width), float(height), 1.0)  # CELLA
    struct.pack_into("<3f", hdr, 52, 90.0, 90.0, 90.0)  # CELLB
    struct.pack_into("<3i", hdr, 64, 1, 2, 3)  # MAPC, MAPR, MAPS
    struct.pack_into("<3f", hdr, 76, 0.0, -1.0, -2.0)  # DMIN/DMAX/DMEAN unset
    struct.pack_into("<i", hdr, 108, 20141)  # NVERSION: MRC2014
    hdr[208:212] = b"MAP "
    hdr[212:216] = b"\x44\x44\x00\x00"  # MACHST: little-endian
    struct.pack_into("<f", hdr, 216, -1.0)  # RMS unset
    labels = (labels or [])[:10]
    struct.pack_into("<i", hdr, 220, len(labels))  # NLABL
    for i, label in enumerate(labels):
        text = label.encode("ascii", "replace")[:80]
        hdr[224 + 80 * i : 224 + 80 * i + len(text)] = text
    return bytes(hdr)


def write_frame(
    path: Path, width: int, height: int, raw: bytes, labels: list[str] | None = None
) -> Path:
    """Write ``raw`` (16 bits per pixel, as from GetAcquiredImage) to ``path``.

    Fails rather than overwrite an existing file.
    """
    if len(raw) != 2 * width * height:
        raise ValueError(f"{len(raw)} bytes is not a {width} x {height} 16-bit image")
    with open(path, "xb") as fh:
        fh.write(mrc_header(width, height, labels))
        fh.write(raw)
    return path


def next_free_path(directory: Path, root: str) -> Path:
    """``<directory>/<root>_NNNN.mrc`` with the first unused number from 0001."""
    n = 1
    while (path := directory / f"{root}_{n:04d}.mrc").exists():
        n += 1
    return path
