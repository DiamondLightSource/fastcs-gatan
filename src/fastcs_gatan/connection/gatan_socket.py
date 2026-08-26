"""GatanSocket wire-protocol client.

fastcs-gatan speaks the same TCP/IP "GatanSocket" protocol as the
SerialEMCCD DigitalMicrograph plugin's socket server. This module does
**not** depend on the ``gatan_client`` package (see ``/workspaces/CLAUDE.md``
and this project's `CLAUDE.md` for the full scope decision) — it is a
reimplementation, ported by hand from
``GatanDetectorClient-0.1.0/gatan_client/gatan_socket.py`` (Apache-2.0,
Copyright 2026 Kyle Dent; see this repo's ``NOTICE`` file), cross-checked
against the MIT-licensed ``/workspaces/SerialEM/BaseSocket.cpp`` +
``GatanSocket.cpp`` + ``Shared/SEMCCDDefines.h``.

Scope implemented here (2026-08-17 session): connection management, status/
capability queries, camera enumeration/selection/insertion, read-mode and
basic shutter/settling configuration, and single-frame acquisition
(``get_acquired_image``). **Not yet implemented**: K2/K3 parameter
configuration (``set_k2_parameters2``), continuous acquisition
(``stop_continuous_camera`` and the streaming loop), and dose-fractionation
with server-side-only frame saving (``setup_file_saving2``,
``get_file_save_result``) — those remain ``NotImplementedError`` stubs for a
future session.

Wire format:

* One message = a 4-byte little-endian length prefix (total bytes including
  itself), then packed arguments grouped *by type* regardless of call-site
  order: all ``long`` args (4-byte int32), then all ``BOOL`` args (4-byte
  int32), then all ``double`` args (8-byte float64), then an optional
  trailing raw long-array payload.
* The first ``long`` sent is always the function code (``FunctionCode``
  below); the first ``long`` received is always a status code (0 = success,
  negative = error, positive = plugin error code from ``SEMCCD_ERRORS``).
* Image-returning calls reply with exactly five longs
  (status, arr_size, width, height, num_chunks), then stream the pixel data
  as ``num_chunks`` chunks; for chunk index > 0 the client must first send a
  bare ``CHUNK_HANDSHAKE`` message before the server sends the next chunk.
"""

from __future__ import annotations

import enum
import socket
import struct
from collections.abc import Sequence


class FunctionCode(enum.IntEnum):
    """``GS_*`` function codes, transcribed from
    ``/workspaces/SerialEM/Shared/SEMCCDDefines.h`` (MIT-licensed, shared
    verbatim with ``SerialEMCCD``). Only entries relevant to the approved v1
    scope are listed here; extend from the same header if scope grows.
    """

    SET_CURRENT_CAMERA = 4
    GET_ACQUIRED_IMAGE = 6
    SELECT_CAMERA = 9
    SET_READ_MODE = 10
    GET_NUMBER_OF_CAMERAS = 11
    IS_CAMERA_INSERTED = 12
    INSERT_CAMERA = 13
    GET_DM_VERSION = 14
    GET_DM_CAPABILITIES = 15
    SET_SHUTTER_NORMALLY_CLOSED = 16
    SET_NO_DM_SETTLING = 17
    SET_K2_PARAMETERS = 23
    CHUNK_HANDSHAKE = 24
    SETUP_FILE_SAVING = 25
    GET_FILE_SAVE_RESULT = 26
    SETUP_FILE_SAVING2 = 27
    SET_K2_PARAMETERS2 = 29
    STOP_CONTINUOUS_CAMERA = 30
    GET_PLUGIN_VERSION = 31
    GET_LAST_ERROR = 32
    GET_LAST_DOSE_RATE = 40
    GET_DM_VERSION_AND_BUILD = 42


FUNCTION_CODES = FunctionCode

# ---- selected constants (Shared/SEMCCDDefines.h, CameraController.h) ----
# processing (GetAcquiredImage)
UNPROCESSED, DARK_SUBTRACTED, GAIN_NORMALIZED = 0, 1, 2
# shuttering
USE_BEAM_BLANK, USE_FILM_SHUTTER, USE_DUAL_SHUTTER = 0, 1, 2
# read modes (K2/K3)
K2_LINEAR_MODE, K2_COUNTING_MODE, K2_SUPERRES_MODE = 0, 1, 2
K3_LINEAR_SET_MODE, K3_COUNTING_SET_MODE = 3, 4

# Error codes (Shared/SEMCCDDefines.h, first enum). 0 == success.
SEMCCD_ERRORS = {
    1: "IMAGE_NOT_FOUND",
    2: "WRONG_DATA_TYPE",
    3: "DM_CALL_EXCEPTION",
    4: "NO_STACK_ID",
    5: "STACK_NOT_3D",
    6: "FILE_OPEN_ERROR",
    7: "SEEK_ERROR",
    8: "WRITE_DATA_ERROR",
    9: "HEADER_ERROR",
    10: "ROTBUF_MEMORY_ERROR",
    11: "DIR_ALREADY_EXISTS",
    12: "DIR_CREATE_ERROR",
    13: "DIR_NOT_EXIST",
    14: "SAVEDIR_IS_FILE",
    15: "DIR_NOT_WRITABLE",
    16: "FILE_ALREADY_EXISTS",
}


class GatanSocketError(RuntimeError):
    """Raised when the plugin returns a non-zero status or the link fails."""


class GatanSocketConnection:
    """Client for the GatanSocket wire protocol.

    Args:
        host: IP address of the machine running DigitalMicrograph.
        port: Must match the ``SERIALEMCCD_PORT`` env var on the DM machine
            (and SerialEM's ``GatanServerPort``). Conventionally 48890.
        timeout: Socket timeout, in seconds, for ordinary calls.
        acq_timeout: Timeout while waiting for/receiving image data, which
            can legitimately take a long time for long exposures.
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 30.0,
        acq_timeout: float = 3600.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.acq_timeout = acq_timeout
        self._sock: socket.socket | None = None

    # ---- Connection ----
    def connect(self) -> None:
        self._sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def __enter__(self) -> GatanSocketConnection:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    # ---- Low-level wire helpers ----
    def _socket(self) -> socket.socket:
        if self._sock is None:
            raise GatanSocketError("not connected")
        return self._sock

    def _recv_exact(self, n: int) -> bytes:
        sock = self._socket()
        chunks: list[bytes] = []
        got = 0
        while got < n:
            block = sock.recv(n - got)
            if not block:
                raise GatanSocketError("connection closed by plugin")
            chunks.append(block)
            got += len(block)
        return b"".join(chunks)

    @staticmethod
    def _pack_request(
        func_code: int,
        longs: Sequence[int] = (),
        bools: Sequence[bool] = (),
        doubles: Sequence[float] = (),
        array: bytes = b"",
    ) -> bytes:
        body = struct.pack(f"<{1 + len(longs)}i", func_code, *longs)
        if bools:
            body += struct.pack(f"<{len(bools)}i", *(1 if b else 0 for b in bools))
        if doubles:
            body += struct.pack(f"<{len(doubles)}d", *doubles)
        body += array
        total = 4 + len(body)
        return struct.pack("<i", total) + body

    def _exchange(
        self,
        func_code: int,
        longs: Sequence[int] = (),
        bools: Sequence[bool] = (),
        doubles: Sequence[float] = (),
        array: bytes = b"",
        n_long_ret: int = 0,
        n_bool_ret: int = 0,
        n_dbl_ret: int = 0,
    ) -> tuple[int, tuple[int, ...], tuple[int, ...], tuple[float, ...]]:
        """Send one function call and decode the reply.

        ``n_*_ret`` counts *actual* return values, not counting the leading
        status long. Returns ``(status, longs, bools, doubles)`` where
        ``longs`` excludes the status word.
        """
        sock = self._socket()
        sock.sendall(self._pack_request(func_code, longs, bools, doubles, array))
        total = struct.unpack("<i", self._recv_exact(4))[0]
        rest = self._recv_exact(total - 4)

        n_long = n_long_ret + 1  # +1 for the status word
        off = 0
        long_vals = struct.unpack_from(f"<{n_long}i", rest, off)
        off += 4 * n_long
        bool_vals = struct.unpack_from(f"<{n_bool_ret}i", rest, off)
        off += 4 * n_bool_ret
        dbl_vals = struct.unpack_from(f"<{n_dbl_ret}d", rest, off)
        status = long_vals[0]
        return status, long_vals[1:], bool_vals, dbl_vals

    def _exchange_image(
        self,
        func_code: int,
        longs: Sequence[int] = (),
        doubles: Sequence[float] = (),
        array: bytes = b"",
        bytes_per_pixel: int = 2,
    ) -> tuple[int, int, bytes]:
        """Send an image-returning call and stream the pixel data back.

        Returns ``(width, height, raw_bytes)``.
        """
        sock = self._socket()
        old_timeout = sock.gettimeout()
        sock.settimeout(self.acq_timeout)
        try:
            sock.sendall(self._pack_request(func_code, longs, (), doubles, array))
            total = struct.unpack("<i", self._recv_exact(4))[0]
            rest = self._recv_exact(total - 4)
            n = len(rest) // 4
            vals = struct.unpack_from(f"<{n}i", rest, 0)
            status = vals[0]
            if n < 5:
                raise GatanSocketError(
                    f"image call {func_code} returned a short reply "
                    f"({n} longs, need at least 5)"
                )
            if status != 0:
                name = SEMCCD_ERRORS.get(abs(status), "unknown")
                raise GatanSocketError(
                    f"image call {func_code} failed: status {status} ({name})"
                )
            arr_size, width, height, num_chunks = vals[1], vals[2], vals[3], vals[4]
            num_bytes = arr_size * bytes_per_pixel
            data = bytearray()
            chunk_size = (num_bytes + num_chunks - 1) // max(num_chunks, 1)
            received = 0
            for chunk in range(num_chunks):
                if chunk:
                    # bare handshake so the server releases the next chunk
                    sock.sendall(self._pack_request(FunctionCode.CHUNK_HANDSHAKE))
                want = min(num_bytes - received, chunk_size)
                data += self._recv_exact(want)
                received += want
            return width, height, bytes(data)
        finally:
            sock.settimeout(old_timeout)

    @staticmethod
    def _check(status: int, what: str) -> None:
        if status != 0:
            name = SEMCCD_ERRORS.get(abs(status), "unknown")
            raise GatanSocketError(f"{what} failed: status {status} ({name})")

    # ---- Status / version ----
    def get_dm_version(self) -> int:
        status, longs, _, _ = self._exchange(FunctionCode.GET_DM_VERSION, n_long_ret=1)
        self._check(status, "GetDMVersion")
        return longs[0]

    def get_dm_version_and_build(self) -> tuple[int, int]:
        status, longs, _, _ = self._exchange(
            FunctionCode.GET_DM_VERSION_AND_BUILD, n_long_ret=2
        )
        self._check(status, "GetDMVersionAndBuild")
        return longs[0], longs[1]

    def get_plugin_version(self) -> int:
        status, longs, _, _ = self._exchange(
            FunctionCode.GET_PLUGIN_VERSION, n_long_ret=1
        )
        self._check(status, "GetPluginVersion")
        return longs[0]

    def get_last_error(self) -> int:
        status, longs, _, _ = self._exchange(FunctionCode.GET_LAST_ERROR, n_long_ret=1)
        self._check(status, "GetLastError")
        return longs[0]

    def get_last_dose_rate(self) -> float:
        status, _, _, doubles = self._exchange(
            FunctionCode.GET_LAST_DOSE_RATE, n_dbl_ret=1
        )
        self._check(status, "GetLastDoseRate")
        return doubles[0]

    def get_dm_capabilities(self) -> tuple[bool, bool, bool]:
        """Returns (can_select_shutter, can_set_settling, open_shutter_works)."""
        status, _, bools, _ = self._exchange(
            FunctionCode.GET_DM_CAPABILITIES, n_bool_ret=3
        )
        self._check(status, "GetDMCapabilities")
        return bool(bools[0]), bool(bools[1]), bool(bools[2])

    # ---- Camera enumeration / selection / insertion ----
    def get_number_of_cameras(self) -> int:
        status, longs, _, _ = self._exchange(
            FunctionCode.GET_NUMBER_OF_CAMERAS, n_long_ret=1
        )
        self._check(status, "GetNumberOfCameras")
        return longs[0]

    def is_camera_inserted(self, camera: int) -> bool:
        status, _, bools, _ = self._exchange(
            FunctionCode.IS_CAMERA_INSERTED, longs=[camera], n_bool_ret=1
        )
        self._check(status, "IsCameraInserted")
        return bool(bools[0])

    def insert_camera(self, camera: int, state: bool) -> None:
        status, *_ = self._exchange(
            FunctionCode.INSERT_CAMERA, longs=[camera], bools=[state]
        )
        self._check(status, "InsertCamera")

    def select_camera(self, camera: int) -> None:
        """Low-level ``GS_SelectCamera``. Prefer :meth:`set_current_camera`
        (matches ``CameraBackend.set_current_camera``'s call site in
        GatanDetectorClient's own adapter) unless a specific reason to use
        this one instead turns up."""
        status, *_ = self._exchange(FunctionCode.SELECT_CAMERA, longs=[camera])
        self._check(status, "SelectCamera")

    def set_current_camera(self, camera: int) -> None:
        status, *_ = self._exchange(FunctionCode.SET_CURRENT_CAMERA, longs=[camera])
        self._check(status, "SetCurrentCamera")

    # ---- Camera mode / settings select + query ----
    def set_read_mode(self, mode: int, scaling: float = 1.0) -> None:
        status, *_ = self._exchange(
            FunctionCode.SET_READ_MODE, longs=[mode], doubles=[scaling]
        )
        self._check(status, "SetReadMode")

    def set_shutter_normally_closed(self, camera: int, shutter: int) -> None:
        status, *_ = self._exchange(
            FunctionCode.SET_SHUTTER_NORMALLY_CLOSED, longs=[camera, shutter]
        )
        self._check(status, "SetShutterNormallyClosed")

    def set_no_dm_settling(self, camera: int) -> None:
        status, *_ = self._exchange(FunctionCode.SET_NO_DM_SETTLING, longs=[camera])
        self._check(status, "SetNoDMSettling")

    def set_k2_parameters2(
        self,
        read_mode: int,
        scaling: float,
        hardware_proc: int,
        dose_frac: bool,
        frame_time: float,
        align_frames: bool,
        save_frames: bool,
        rotation_flip: int,
        flags: int,
    ) -> None:
        raise NotImplementedError(
            "K2/K3 parameter configuration is deferred — out of scope for "
            "this session's single-acquisition + mode-selection work"
        )

    # ---- Acquisition: single-frame (and, with continuous bits OR'd into
    # `processing`, continuous — but the continuous streaming loop itself is
    # not implemented yet) ----
    def get_acquired_image(
        self,
        width: int,
        height: int,
        processing: int = GAIN_NORMALIZED,
        exposure: float = 1.0,
        binning: int = 1,
        top: int = 0,
        left: int = 0,
        bottom: int = 0,
        right: int = 0,
        shutter: int = USE_BEAM_BLANK,
        settling: float = 0.0,
        shutter_delay: int = 0,
        divide_by_2: int = 0,
        corrections: int = 0,
    ) -> tuple[int, int, bytes]:
        """Single-frame acquisition.

        ``width``/``height`` are the expected *binned* output dimensions;
        ``top``/``left``/``bottom``/``right`` are the binned readout
        coordinates — leave ``bottom``/``right`` at 0 to default to the full
        ``height``/``width``. Returns ``(width, height, raw_int16_bytes)``.
        """
        if bottom == 0:
            bottom = height
        if right == 0:
            right = width
        arr_size = width * height
        longs = [
            arr_size,
            width,
            height,
            processing,
            binning,
            top,
            left,
            bottom,
            right,
            shutter,
            shutter_delay,
            divide_by_2,
            corrections,
        ]
        doubles = [exposure, settling]
        return self._exchange_image(
            FunctionCode.GET_ACQUIRED_IMAGE,
            longs=longs,
            doubles=doubles,
            bytes_per_pixel=2,
        )

    def stop_continuous_camera(self) -> None:
        raise NotImplementedError(
            "continuous acquisition is deferred — out of scope for this "
            "session's single-acquisition + mode-selection work"
        )

    # ---- Dose fractionation to server-side storage only (deferred) ----
    def setup_file_saving2(
        self,
        rotation_flip: int,
        file_per_image: bool,
        pixel_size: float,
        flags: int,
        save_dir: str,
        root_name: str,
    ) -> int:
        raise NotImplementedError(
            "dose-fractionation-to-disk is deferred — out of scope for this "
            "session's single-acquisition + mode-selection work"
        )

    def get_file_save_result(self) -> tuple[int, int]:
        raise NotImplementedError(
            "dose-fractionation-to-disk is deferred — out of scope for this "
            "session's single-acquisition + mode-selection work"
        )
