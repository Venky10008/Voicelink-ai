"""Diagnostic: walk the EBML elements of a captured webm file.

Robustly skips invalid regions (the file may start mid-data). Prints
SimpleBlock timestamps and cluster offsets so we can see whether the file
begins at the start of the stream or in the middle.

Usage: voice-venv/Scripts/python.exe inspect_webm.py <file.webm>
"""
import struct
import sys

CLUSTER = 0x1F43B675
SIMPLE_BLOCK = 0xA3
BLOCK_GROUP = 0xA0


def read_vint(data: bytes, pos: int):
    b = data[pos]
    mask = 0x80
    length = 1
    while not (b & mask):
        if mask == 0x01:
            raise ValueError("invalid vint")
        mask >>= 1
        length += 1
    value = b & (mask - 1)
    for i in range(1, length):
        value = (value << 8) | data[pos + i]
    return value, length


def id_length(first: int) -> int:
    if first & 0x80:
        return 1
    if first & 0x40:
        return 2
    if first & 0x20:
        return 3
    if first & 0x10:
        return 4
    return 0


def main() -> None:
    path = sys.argv[1]
    data = open(path, "rb").read()
    ebml_magic = b"\x1a\x45\xdf\xa3"
    print(f"file: {path}  ({len(data)} bytes)")
    print(f"starts with EBML magic: {data[:4] == ebml_magic}")

    pos = 0
    cluster_times: list[int] = []
    block_ts: list[int] = []
    while pos < len(data) - 8:
        idlen = id_length(data[pos])
        if idlen == 0:
            pos += 1  # skip garbage byte and continue
            continue
        eid = 0
        for i in range(idlen):
            eid = (eid << 8) | data[pos + i]
        try:
            size, sizelen = read_vint(data, pos + idlen)
        except (ValueError, IndexError):
            pos += 1
            continue

        # Cluster: read its inner Timestamp element (0xE7) right after the header.
        if eid == CLUSTER:
            p = pos + idlen + sizelen
            ts = None
            if p + 2 < len(data) and data[p] == 0xE7:
                try:
                    v, l = read_vint(data, p + 1)
                    ts = v
                except (ValueError, IndexError):
                    ts = None
            cluster_times.append(ts)
            pos = p
            continue

        if eid == SIMPLE_BLOCK and size is not None and size < 1 << 20:
            p = pos + idlen + sizelen
            if p + 4 < len(data):
                ts = struct.unpack(">h", data[p + 1 : p + 3])[0]
                block_ts.append(ts)
            pos = p + size
            continue

        if size == 0x01FFFFFFFFFFFFFF:  # unknown size — can't skip, stop
            break
        pos += idlen + sizelen

    print(f"clusters: {len(cluster_times)}")
    print(f"cluster timestamps (ms): {cluster_times[:30]}")
    print(f"first 40 block timestamps (ms): {block_ts[:40]}")
    print(f"min block ts: {min(block_ts) if block_ts else 'n/a'}, "
          f"max block ts: {max(block_ts) if block_ts else 'n/a'}")


if __name__ == "__main__":
    main()
