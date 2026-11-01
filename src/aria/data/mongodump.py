"""Read a ``mongodump --archive`` stream: which collection each BSON document belongs to.

The archive starts with a magic number and a prelude (a header document and one metadata
document per collection, ended by a terminator). Then come blocks: a namespace document naming
the collection, that collection's documents, and a terminator. Collections are dumped several
at a time, so their blocks interleave. ``mongodump --gzip --archive`` gzips the whole stream.

Only what reading needs is here: a small BSON decoder for the types a dump holds, written for
this format so no MongoDB driver is needed. The data is untrusted, so every length is checked
before it is used.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

MAGIC = b"\x6d\xe2\x99\x81"
GZIP_MAGIC = b"\x1f\x8b"
TERMINATOR = -1
_INT32 = struct.Struct("<i")
_INT64 = struct.Struct("<q")
_DOUBLE = struct.Struct("<d")
_MAX_DOCUMENT = 64 << 20  # BSON documents are at most 16 MiB; anything far larger is corrupt


class ArchiveError(ValueError):
    pass


def _cstring(data: bytes, at: int) -> tuple[str, int]:
    end = data.find(b"\x00", at)
    if end < 0:
        msg = "unterminated BSON string"
        raise ArchiveError(msg)
    return data[at:end].decode("utf-8", "replace"), end + 1


def _int32(data: bytes, at: int) -> int:
    if at + 4 > len(data):
        msg = "truncated BSON value"
        raise ArchiveError(msg)
    return int(_INT32.unpack_from(data, at)[0])


def decode(data: bytes, at: int = 0) -> tuple[dict[str, Any], int]:
    """One BSON document starting at ``at``: the document and where the next one starts."""
    size = _int32(data, at)
    end = at + size
    if size < 5 or end > len(data) or data[end - 1] != 0:
        msg = "malformed BSON document"
        raise ArchiveError(msg)
    out: dict[str, Any] = {}
    i = at + 4
    while i < end - 1:
        kind = data[i]
        key, i = _cstring(data, i + 1)
        out[key], i = _value(kind, data, i, end)
    return out, end


def _value(kind: int, data: bytes, i: int, end: int) -> tuple[Any, int]:
    if i > end:
        msg = "truncated BSON value"
        raise ArchiveError(msg)
    if kind == 0x01:  # double
        return _DOUBLE.unpack_from(data, i)[0], i + 8
    if kind in (0x02, 0x0D, 0x0E):  # string, JavaScript code, symbol
        n = _int32(data, i)
        if n < 1 or i + 4 + n > end:
            msg = "malformed BSON string"
            raise ArchiveError(msg)
        return data[i + 4 : i + 3 + n].decode("utf-8", "replace"), i + 4 + n
    if kind == 0x03:  # embedded document
        return decode(data, i)
    if kind == 0x04:  # array: a document keyed "0", "1", ...
        doc, j = decode(data, i)
        return list(doc.values()), j
    if kind == 0x05:  # binary: kept as its length only
        n = _int32(data, i)
        return f"<{n} bytes>", i + 5 + n
    if kind in (0x06, 0x0A, 0x7F, 0xFF):  # undefined, null, max key, min key
        return None, i
    if kind == 0x07:  # ObjectId
        return data[i : i + 12].hex(), i + 12
    if kind == 0x08:  # boolean
        return data[i] == 1, i + 1
    if kind == 0x09:  # UTC datetime, milliseconds since the epoch
        ms = _INT64.unpack_from(data, i)[0]
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC), i + 8
        except (OverflowError, OSError, ValueError):
            return None, i + 8
    if kind == 0x0B:  # regular expression: pattern and options
        pattern, i = _cstring(data, i)
        _, i = _cstring(data, i)
        return pattern, i
    if kind == 0x0F:  # code with scope
        return None, i + _int32(data, i)
    if kind == 0x10:  # int32
        return _int32(data, i), i + 4
    if kind in (0x11, 0x12):  # timestamp, int64
        return _INT64.unpack_from(data, i)[0], i + 8
    if kind == 0x13:  # decimal128: kept as hex, never needed here
        return data[i : i + 16].hex(), i + 16
    msg = f"unknown BSON type {kind:#04x}"
    raise ArchiveError(msg)


def _plain(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """The archive's bytes, gunzipped when the stream is gzipped (``--gzip --archive``)."""
    gunzip: Any = None
    head = b""
    for chunk in chunks:
        data = chunk
        if gunzip is None:  # undecided until the first two bytes have arrived
            head += chunk
            if len(head) < len(GZIP_MAGIC):
                continue
            magic = head.startswith(GZIP_MAGIC)
            gunzip = zlib.decompressobj(16 + zlib.MAX_WBITS) if magic else False
            data, head = head, b""
        plain = gunzip.decompress(data) if gunzip else data
        if plain:
            yield plain
    if gunzip is None and head:
        yield head


def documents(chunks: Iterable[bytes]) -> Iterator[tuple[str, bytes]]:
    """(collection, raw BSON document) for every document in the archive, in stream order.

    Documents are returned undecoded, so a reader can skip the collections it does not keep
    without paying to decode them.
    """
    buffer = bytearray()
    at = 0
    state = "magic"
    collection: str | None = None
    for data in _plain(chunks):
        buffer += data
        while True:
            if state == "magic":
                if len(buffer) - at < 4:
                    break
                if bytes(buffer[at : at + 4]) != MAGIC:
                    msg = "not a mongodump archive"
                    raise ArchiveError(msg)
                at += 4
                state = "prelude"
                continue
            if len(buffer) - at < 4:
                break
            size = _INT32.unpack_from(buffer, at)[0]
            if size == TERMINATOR:
                at += 4
                state = "blocks" if state == "prelude" else state
                collection = None
                continue
            if size < 5 or size > _MAX_DOCUMENT:
                msg = f"implausible document size {size}"
                raise ArchiveError(msg)
            if len(buffer) - at < size:
                break
            body = bytes(buffer[at : at + size])
            at += size
            if state == "prelude":
                continue
            if collection is None:
                header, _ = decode(body)
                collection = str(header.get("collection") or "")
                continue
            yield collection, body
        if at > _MAX_DOCUMENT:
            del buffer[:at]
            at = 0
