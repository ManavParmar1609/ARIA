"""Read one file inside a zip on a web server without downloading the rest of the zip.

A zip lists its members at its end, so a few HTTP range requests find a member's offset, and
one more request streams that member's bytes, which are inflated as they arrive. The caller
reads as much as it needs and closes the stream. Used for the Public Jira Dataset, whose only
data is one 5.8 GB member: ARIA keeps a small subset of it and never stores the whole file.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx

_BLOCK = 1 << 16  # bytes fetched per range request while reading the zip's directory
_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_LOCAL_MAGIC = 0x04034B50
RESUMES = 5  # times a member stream cut off part way is picked up again


class RemoteZipError(RuntimeError):
    pass


class RangeFile(io.RawIOBase):
    """A read-only, seekable view of a remote file, fetched by HTTP range requests.

    ``before`` runs before every request (a throttle for hosts that refuse bursts).
    """

    def __init__(
        self, client: httpx.Client, url: str, *, before: Callable[[], None] | None = None
    ) -> None:
        super().__init__()
        self._client = client
        self._url = url
        self._before = before or (lambda: None)
        self._pos = 0
        self._cache_start = 0
        self._cache = b""
        probe = self._get(0, 0)
        total = probe.headers.get("content-range", "").rpartition("/")[2]
        if not total.isdigit():
            msg = f"{url} does not answer range requests"
            raise RemoteZipError(msg)
        self.size = int(total)

    def _get(self, start: int, end: int) -> httpx.Response:
        self._before()
        response = self._client.get(self._url, headers={"Range": f"bytes={start}-{end}"})
        if response.status_code != httpx.codes.PARTIAL_CONTENT:
            msg = f"range request to {self._url} returned {response.status_code}"
            raise RemoteZipError(msg)
        return response

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self._pos
        end = min(self.size, self._pos + size)
        if end <= self._pos:
            return b""
        cached_end = self._cache_start + len(self._cache)
        if not (self._cache_start <= self._pos and end <= cached_end):
            fetch_end = min(self.size, max(end, self._pos + _BLOCK)) - 1
            self._cache = self._get(self._pos, fetch_end).content
            self._cache_start = self._pos
        offset = self._pos - self._cache_start
        data = self._cache[offset : offset + (end - self._pos)]
        self._pos += len(data)
        return data

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


@dataclass(frozen=True)
class Member:
    name: str
    data_offset: int  # where the member's (compressed) bytes start in the zip
    compress_type: int
    compress_size: int
    file_size: int
    crc: int = 0  # the CRC-32 the zip records for the member's bytes


def locate(
    client: httpx.Client, url: str, name: str, *, before: Callable[[], None] | None = None
) -> Member:
    """Where member ``name`` of the zip at ``url`` starts, read from the zip's directory."""
    remote = RangeFile(client, url, before=before)
    with zipfile.ZipFile(remote) as bundle:
        try:
            info = bundle.getinfo(name)
        except KeyError:
            msg = f"{name} is not in {url}"
            raise RemoteZipError(msg) from None
    remote.seek(info.header_offset)
    header = remote.read(_LOCAL_HEADER.size)
    fields = _LOCAL_HEADER.unpack(header)
    if fields[0] != _LOCAL_MAGIC:
        msg = f"{name}: no local file header at offset {info.header_offset}"
        raise RemoteZipError(msg)
    name_length, extra_length = fields[9], fields[10]
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        msg = f"{name}: compression method {info.compress_type} is not supported"
        raise RemoteZipError(msg)
    return Member(
        name=name,
        data_offset=info.header_offset + _LOCAL_HEADER.size + name_length + extra_length,
        compress_type=info.compress_type,
        compress_size=info.compress_size,
        file_size=info.file_size,
        crc=info.CRC,
    )


def stream(
    client: httpx.Client,
    url: str,
    member: Member,
    *,
    before: Callable[[], None] | None = None,
) -> Iterator[bytes]:
    """The member's bytes, inflated as they arrive. Stop iterating to stop the download.

    A connection cut off part way is picked up where it stopped, with a new range request, up
    to ``RESUMES`` times: the bytes are the same either way, so the inflater never notices.
    A member read to its end is checked against the CRC-32 the zip records for it.
    """
    end = member.data_offset + member.compress_size - 1
    inflate = zlib.decompressobj(-zlib.MAX_WBITS)
    deflated = member.compress_type == zipfile.ZIP_DEFLATED
    received = 0
    resumes = 0
    crc = 0
    while member.data_offset + received <= end:
        (before or (lambda: None))()
        headers = {"Range": f"bytes={member.data_offset + received}-{end}"}
        try:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code != httpx.codes.PARTIAL_CONTENT:
                    msg = f"range request to {url} returned {response.status_code}"
                    raise RemoteZipError(msg)
                for chunk in response.iter_bytes():  # as they arrive, so a cut loses none
                    received += len(chunk)
                    data = inflate.decompress(chunk) if deflated else chunk
                    if data:
                        crc = zlib.crc32(data, crc)
                        yield data
        except httpx.TransportError:
            resumes += 1
            if resumes > RESUMES:
                raise
            continue
        break
    if deflated and (tail := inflate.flush()):
        crc = zlib.crc32(tail, crc)
        yield tail
    if member.crc and crc != member.crc:
        msg = f"{member.name}: CRC-32 mismatch (the zip records {member.crc:08x}, got {crc:08x})"
        raise RemoteZipError(msg)
