"""Wire-format tests using a loopback socket pair — no DigitalMicrograph or
mock server needed. Adapted from the self-test in the porting source,
GatanDetectorClient-0.1.0/gatan_client/gatan_socket.py (not depended on,
just used as the reference this test's expected wire bytes were checked
against during scaffolding).
"""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from fastcs_gatan.connection.gatan_socket import (
    FunctionCode,
    GatanSocketConnection,
    GatanSocketError,
    saved_frames_path,
)


def _recv_packet(sock: socket.socket) -> tuple[int, bytes]:
    header = b""
    while len(header) < 4:
        header += sock.recv(4 - len(header))
    total = struct.unpack("<i", header)[0]
    body = b""
    while len(body) < total - 4:
        body += sock.recv(total - 4 - len(body))
    return total, body


def _connection_over(sock: socket.socket) -> GatanSocketConnection:
    conn = GatanSocketConnection(host="unused", port=0)
    conn._sock = sock  # bypass connect(): drive an already-open test socket
    return conn


def test_no_arg_call_get_dm_version():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            total, body = _recv_packet(server_sock)
            func = struct.unpack_from("<i", body, 0)[0]
            assert total == 8
            assert func == FunctionCode.GET_DM_VERSION
            # reply: status 0, version 50302
            server_sock.sendall(struct.pack("<iii", 12, 0, 50302))

        t = threading.Thread(target=server)
        t.start()
        version = conn.get_dm_version()
        t.join()

        assert version == 50302
    finally:
        client_sock.close()
        server_sock.close()


def test_camera_selection_and_insertion():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            # GetNumberOfCameras
            _total, body = _recv_packet(server_sock)
            assert struct.unpack_from("<i", body, 0)[0] == (
                FunctionCode.GET_NUMBER_OF_CAMERAS
            )
            server_sock.sendall(struct.pack("<iii", 12, 0, 2))

            # SetCurrentCamera(1)
            _total, body = _recv_packet(server_sock)
            func, camera = struct.unpack_from("<2i", body, 0)
            assert func == FunctionCode.SET_CURRENT_CAMERA
            assert camera == 1
            server_sock.sendall(struct.pack("<ii", 8, 0))

            # IsCameraInserted(1) -> True
            _total, body = _recv_packet(server_sock)
            func, camera = struct.unpack_from("<2i", body, 0)
            assert func == FunctionCode.IS_CAMERA_INSERTED
            assert camera == 1
            server_sock.sendall(struct.pack("<iii", 12, 0, 1))

        t = threading.Thread(target=server)
        t.start()
        assert conn.get_number_of_cameras() == 2
        conn.set_current_camera(1)
        assert conn.is_camera_inserted(1) is True
        t.join()
    finally:
        client_sock.close()
        server_sock.close()


def test_set_read_mode_packs_long_and_double():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            _total, body = _recv_packet(server_sock)
            func, mode = struct.unpack_from("<2i", body, 0)
            (scaling,) = struct.unpack_from("<d", body, 8)
            assert func == FunctionCode.SET_READ_MODE
            assert mode == 4  # K3_COUNTING_SET_MODE
            assert abs(scaling - 1.0) < 1e-9
            server_sock.sendall(struct.pack("<ii", 8, 0))

        t = threading.Thread(target=server)
        t.start()
        conn.set_read_mode(4, 1.0)
        t.join()
    finally:
        client_sock.close()
        server_sock.close()


def test_single_frame_acquisition_with_chunked_transfer():
    """Single-frame acquisition (GetAcquiredImage) over a 2-chunk transfer,
    including the mid-transfer chunk handshake."""
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)
        width, height = 4, 3
        npix = width * height
        payload = struct.pack(f"<{npix}h", *range(npix))

        def server():
            _total, body = _recv_packet(server_sock)
            func = struct.unpack_from("<i", body, 0)[0]
            assert func == FunctionCode.GET_ACQUIRED_IMAGE
            num_chunks = 2
            # reply args: status, arr_size, width, height, num_chunks
            server_sock.sendall(
                struct.pack("<iiiiii", 24, 0, npix, width, height, num_chunks)
            )
            nbytes = npix * 2
            chunk_size = (nbytes + num_chunks - 1) // num_chunks
            server_sock.sendall(payload[:chunk_size])  # chunk 0, no handshake needed

            # expect a handshake before chunk 1
            _total2, body2 = _recv_packet(server_sock)
            assert struct.unpack_from("<i", body2, 0)[0] == (
                FunctionCode.CHUNK_HANDSHAKE
            )
            server_sock.sendall(payload[chunk_size:])  # chunk 1

        t = threading.Thread(target=server)
        t.start()
        aw, ah, data = conn.get_acquired_image(width, height, exposure=0.5)
        t.join()

        assert (aw, ah) == (width, height)
        assert data == payload
    finally:
        client_sock.close()
        server_sock.close()


def test_set_k2_parameters2_wire_layout():
    """Cross-checked against SerialEM/GatanSocket.cpp CGatanSocket::
    SetK2Parameters2: longs, then bools, then doubles, then filter array."""
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            total, body = _recv_packet(server_sock)
            longs = struct.unpack_from("<6i", body, 0)
            bools = struct.unpack_from("<3i", body, 24)
            doubles = struct.unpack_from("<6d", body, 36)
            array = body[84:]
            assert longs == (FunctionCode.SET_K2_PARAMETERS2, 4, 0, 2, 0, 1)
            assert bools == (1, 0, 1)
            assert doubles == (1.0, 0.05, 0.0, 0.0, 0.0, 0.0)
            assert array == b"\x00\x00\x00\x00"  # empty filter name + NUL
            assert total == 4 + len(body)
            server_sock.sendall(struct.pack("<ii", 8, 0))

        t = threading.Thread(target=server)
        t.start()
        conn.set_k2_parameters2(
            read_mode=4,
            scaling=1.0,
            hardware_proc=0,
            dose_frac=True,
            frame_time=0.05,
            align_frames=False,
            save_frames=True,
            rotation_flip=2,
            flags=0,
        )
        t.join()
    finally:
        client_sock.close()
        server_sock.close()


def test_setup_file_saving2_wire_layout_and_error_word():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            _total, body = _recv_packet(server_sock)
            func, rot_flip, flags, name_size = struct.unpack_from("<4i", body, 0)
            (file_per_image,) = struct.unpack_from("<i", body, 16)
            doubles = struct.unpack_from("<5d", body, 20)
            names = body[60:]
            assert func == FunctionCode.SETUP_FILE_SAVING2
            assert (rot_flip, flags, file_per_image) == (0, 0, 0)
            assert doubles == (1.5, 0.0, 0.0, 0.0, 0.0)
            assert len(names) == 4 * name_size
            assert names.rstrip(b"\x00").split(b"\x00") == [b"D:\\frames", b"m1"]
            # reply: status 0, error word 13 (DIR_NOT_EXIST)
            server_sock.sendall(struct.pack("<iii", 12, 0, 13))

        t = threading.Thread(target=server)
        t.start()
        err = conn.setup_file_saving2(
            rotation_flip=0,
            file_per_image=False,
            pixel_size=1.5,
            flags=0,
            save_dir="D:\\frames",
            root_name="m1",
        )
        t.join()
        assert err == 13
    finally:
        client_sock.close()
        server_sock.close()


def test_get_file_save_result():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            _total, body = _recv_packet(server_sock)
            assert struct.unpack_from("<i", body, 0)[0] == (
                FunctionCode.GET_FILE_SAVE_RESULT
            )
            server_sock.sendall(struct.pack("<iiii", 16, 0, 40, 0))

        t = threading.Thread(target=server)
        t.start()
        assert conn.get_file_save_result() == (40, 0)
        t.join()
    finally:
        client_sock.close()
        server_sock.close()


def test_image_error_reply_reports_status():
    """An error reply to an image call carries only the status word."""
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)

        def server():
            _recv_packet(server_sock)
            server_sock.sendall(struct.pack("<ii", 8, 26))

        t = threading.Thread(target=server)
        t.start()
        with pytest.raises(GatanSocketError, match="GENERAL_SCRIPT_ERROR"):
            conn.get_acquired_image(4, 4)
        t.join()
    finally:
        client_sock.close()
        server_sock.close()


def test_exclusive_rejects_other_threads():
    client_sock, server_sock = socket.socketpair()
    try:
        conn = _connection_over(client_sock)
        errors: list[Exception] = []

        def other_thread():
            try:
                conn.get_dm_version()
            except GatanSocketError as e:
                errors.append(e)

        with conn.exclusive():
            t = threading.Thread(target=other_thread)
            t.start()
            t.join()
        assert len(errors) == 1
        assert "busy" in str(errors[0])
    finally:
        client_sock.close()
        server_sock.close()


@pytest.mark.parametrize(
    "flags, file_per_image, expected",
    [
        (0, False, "D:\\frames\\m1.mrc"),
        (1 << 16, False, "D:\\frames\\m1.mrcs"),
        (1 << 3, False, "D:\\frames\\m1.tif"),
        (0, True, "D:\\frames\\m1\\"),
    ],
)
def test_saved_frames_path(flags, file_per_image, expected):
    assert saved_frames_path("D:\\frames", "m1", flags, file_per_image) == expected
