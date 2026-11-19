import os
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request


HANDSHAKE_SIZE = 1536
HOST = "127.0.0.1"
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
admin_url = sys.argv[1] + "/admin?"


def admin(**params):
    with http.open(admin_url + urllib.parse.urlencode(params), timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {response.status}")


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise EOFError(f"Expected {size} bytes, received {len(data)}")
    return data


def read_until(stream, marker):
    data = bytearray()
    while marker not in data and len(data) < 8192:
        block = stream.read1(4096)
        if not block:
            break
        data.extend(block)
    if marker not in data:
        raise RuntimeError(f"RTMP response did not contain {marker!r}")


with socket.create_server((HOST, 0)) as listener:
    listener.settimeout(10)
    port = listener.getsockname()[1]
    admin(cmd="fetch", name="RTMP pull smoke test", url=f"rtmp://{HOST}:{port}/live/test", type="FLV")
    sock, _ = listener.accept()
    with sock, sock.makefile("rb") as stream:
        sock.settimeout(5)
        if read_exact(stream, 1) != b"\x03":
            raise RuntimeError("PeerCast did not request RTMP version 3")
        c1 = read_exact(stream, HANDSHAKE_SIZE)
        s1 = bytes(HANDSHAKE_SIZE)
        sock.sendall(b"\x03" + s1 + c1)
        read_exact(stream, HANDSHAKE_SIZE)
        read_until(stream, b"\x02\x00\x07connect")
print("PeerCast RTMP fetch sent connect after the handshake")

port = 11935
admin(cmd="control_rtmp", action="start", name="RTMP ingest smoke test", port=port)
try:
    for attempt in range(30):
        try:
            sock = socket.create_connection((HOST, port), timeout=1)
            break
        except ConnectionRefusedError:
            if attempt == 29:
                raise
            time.sleep(0.2)

    with sock, sock.makefile("rb") as stream:
        sock.settimeout(5)
        c1 = bytes(8) + os.urandom(HANDSHAKE_SIZE - 8)
        sock.sendall(b"\x03" + c1)
        if read_exact(stream, 1) != b"\x03":
            raise RuntimeError("RTMP server did not respond with version 3")
        s1 = read_exact(stream, HANDSHAKE_SIZE)
        if read_exact(stream, HANDSHAKE_SIZE) != c1:
            raise RuntimeError("RTMP server did not echo C1")
        # AMF0 connect, transaction ID 1, and an object with app=live.
        connect = b"\x02\x00\x07connect\x00" + struct.pack(">d", 1)
        connect += b"\x03\x00\x03app\x02\x00\x04live\x00\x00\x09"
        header = b"\x03" + bytes(3) + len(connect).to_bytes(3, "big") + b"\x14" + bytes(4)
        sock.sendall(s1 + header + connect)
        read_until(stream, b"NetConnection.Connect.Success")
    print("Packaged RTMP server accepted connect after the handshake")
finally:
    admin(cmd="control_rtmp", action="stop")
