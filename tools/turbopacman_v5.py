#!/usr/bin/env python3

# mirrorlist_v5.py -- Download what pacman needs from the fastest Arch Linux mirrors.
# Written in 2026 by Claude.

# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

# Finding and filtering mirrors follows mirrorlist.py, written in 2025 by Ruud
# van Asseldonk. This version replaces pacman's download step:
#
#  1. Refresh the repository databases from the mirror the log rates best.
#  2. Ask pacman what it wants to download.
#  3. Download it over lanes, one connection to one mirror each, and open
#     another lane while the link has room and the job would finish sooner
#     by more than a lane costs.
#  4. Write the mirrors with the best rate in nine runs out of ten to a
#     mirrorlist of our own, for what pacman still downloads itself.
#
# Whether the link has room we read from its queue: a full link delays
# every lane's round trip by the same amount. What a mirror delivered in a
# run, as a share of the run's highest total, is its own level plus what
# lanes that opened as it did get: with room, or joining a full link, where
# a lane keeps a small share. From those we hold a belief about each
# mirror's level, and each run draws its lanes from it. The log of every run
# is an SQLite file.

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import os
import random
import shutil
import socket
import sqlite3
import ssl
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set
from urllib.parse import urlparse

STATUS_URL = "https://archlinux.org/mirrors/status/json/"
COUNTRIES = {"NL", "BE", "DE", "DK", "SE", "NO"}
USER_AGENT = "Turbopacman"

SAMPLE_BYTES = 100_000
READ_BYTES = 32 * 1024
CONNECT_TIMEOUT_SEC = 10.0
STATUS_TIMEOUT_SEC = 30.0

# With each sample we log these fields of the kernel's struct tcp_info
# (linux/tcp.h), all 32-bit, by their byte offset; see the samples table.
TCP_INFO_OFFSETS = {
    "rtt_us": 68,
    "min_rtt_us": 148,
    "rcv_rtt_us": 92,
    "rcv_space_bytes": 96,
    "data_segs_in": 152,
    "ooo_packets": 224,
}

# A mirror that sends nothing for this long has stalled: in the v4 log, 3 of
# 92,967 gaps between samples were longer, all on mirrors slowing down.
STALL_SEC = 3.0

# Larger files are requested in pieces, so that one 156 MB package cannot
# decide on its own when the download finishes.
CHUNK_BYTES = 2_000_000

# The job list gives no size for signatures; real ones are 118 to 590 bytes.
SIGNATURE_BYTES = 300

# How much work we keep requested from a mirror, in seconds at its rate:
# enough that it never waits for a request, and no more, because a sent
# request cannot be moved to another mirror.
REQUESTED_SEC = 0.5

# The lanes are steered every TICK_SEC, well within REQUESTED_SEC.
TICK_SEC = 0.1

# A new connection takes about this long to reach its speed (0.45 s for the
# fast probes of the v4 log), so a change has to gain at least this much.
RAMP_SEC = 0.5

# A rate is the bytes of the last READING_SEC. Over less time, rates disagreed
# with longer ones of the same mirror.
READING_SEC = 1.0

# A full link queues: every lane's round trip rises by the same delay. The
# link is full while the two lanes that deliver most both have a round trip
# QUEUE_FULL_SEC or more above the lowest the kernel saw on their connection.
# One lane cannot tell: a slow mirror's own path, or a sender that paces its
# data, raises its round trip as a queue at our link does, but not another
# mirror's. A lane that joined a full link has the queue in its lowest at
# first, but the queue comes and goes and its lowest soon holds none: of 720
# such lanes in the v5 logs, 1% read room most of the time. On iso5 at the
# ceiling the queue was 46.5 ms (median), and 0.9 ms below half of it.
QUEUE_FULL_SEC = 0.010

# For a young log, the crowd's level (a mirror's rate over the ceiling, in
# log), how much the mirrors' levels spread and how far a ball strays from its
# mirror's; and the rounds of fitting (see Speeds).
SEEDED_LEVEL = math.log(0.1)
SEEDED_SPREAD = 1.5
SEEDED_NOISE = 1.0
SPEED_ROUNDS = 10

# The mirrors we write for pacman, for what it still downloads itself. The
# file is our own, as the pacman-mirrorlist package owns
# /etc/pacman.d/mirrorlist; pacman reads ours where pacman.conf has
# `Include = /etc/pacman.d/mirrorlist-turbo`, which the user adds after a
# first run: pacman refuses a pacman.conf that includes a missing file.
MIRRORLIST_PATH = "/etc/pacman.d/mirrorlist-turbo"
N_MIRRORLIST = 5

# What one more mirror on the screen costs, in seconds of the download: a
# lane opens only if it would save more than this and RAMP_SEC.
MIRROR_SEC = 0.5

# The databases come only from a mirror we believe delivers at least this
# share of the best one's rate, so that a draw costs at most about twice the
# refresh (see run).
REFRESH_SHARE = 0.5

# Why we end a lane: it holds requests it would take longer to deliver than
# the other lanes would take for the rest of the job, or the job is done.
TOO_SLOW = "too slow"
JOB_DONE = "the job is done"

# While developing, we leave a mirror alone for this long after using it.
COOLDOWN_SEC = 900.0

# The screen is redrawn every REDRAW_SEC, with rates over about SHOWN_RATE_SEC
# and a time left that moves toward bytes over rate with SHOWN_LEFT_SEC.
REDRAW_SEC = 0.2
SHOWN_RATE_SEC = 5.0
SHOWN_LEFT_SEC = 1.0

# TimeoutError and ssl.SSLError are subclasses of OSError.
NETWORK_ERRORS = (OSError, EOFError, asyncio.LimitOverrunError, ValueError)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))


class Mirror(NamedTuple):
    """The fields of <https://archlinux.org/mirrors/status/> that we use."""

    active: bool
    # Between 0.0 and 1.0, not a percentage.
    completion_pct: float
    country_code: str
    # Average mirroring delay, in seconds.
    delay: Optional[int]
    last_sync: Optional[str]
    protocol: str
    url: str

    @classmethod
    def from_json(cls, entry: Dict[str, Any]) -> Mirror:
        return cls(**{k: entry[k] for k in cls._fields})

    def is_ok(self, country_codes: Set[str]) -> bool:
        """Return whether we want this mirror in our final list."""
        return (
            self.active
            and (self.protocol == "https")
            and (self.country_code in country_codes)
            and (self.completion_pct == 1.0)
        )

    def is_fresh(self, now: datetime) -> bool:
        """Less than an hour behind on average, and synced in the last 90 min."""
        if self.delay is None or self.last_sync is None:
            return False
        dt = now - datetime.fromisoformat(self.last_sync)
        return (self.delay < 3600) and (dt < timedelta(minutes=90))

    def hostname(self) -> str:
        h = urlparse(self.url).hostname
        assert h is not None, "Mirror urls must have a hostname"
        return h

    def port(self) -> int:
        return urlparse(self.url).port or 443


async def get_mirrors() -> tuple[str, List[Mirror]]:
    """Fetch the mirror status. Return the part we keep in the log, which is
    the mirrors in our countries with numbers rounded, and every mirror."""

    def get() -> str:
        request = urllib.request.Request(STATUS_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=STATUS_TIMEOUT_SEC) as r:
            return str(r.read().decode("utf-8"))

    status = json.loads(await asyncio.to_thread(get))
    mirrors = [Mirror.from_json(e) for e in status["urls"]]
    status["urls"] = [
        {k: round(v, 3) if isinstance(v, float) else v for k, v in e.items()}
        for e in status["urls"]
        if e["country_code"] in COUNTRIES
    ]
    return json.dumps(status, separators=(",", ":")), mirrors


def filter_mirrors(mirrors: List[Mirror], now: datetime) -> List[Mirror]:
    return [m for m in mirrors if m.is_ok(COUNTRIES) and m.is_fresh(now)]


class Chunk(NamedTuple):
    """One request: a whole file, or a byte range of one."""

    # Like "core/os/x86_64/core.db", relative to a mirror's base url.
    path: str
    # Bytes expected, or 0 if unknown.
    size_bytes: int = 0
    # Where the range starts in the file, or None to request the whole file.
    offset_bytes: Optional[int] = None


def split_file(path: str, size_bytes: int) -> List[Chunk]:
    if size_bytes <= CHUNK_BYTES:
        return [Chunk(path, size_bytes)]
    return [
        Chunk(path, min(CHUNK_BYTES, size_bytes - offset), offset)
        for offset in range(0, size_bytes, CHUNK_BYTES)
    ]


class Output:
    """Writes chunks, which arrive out of order, at their offsets in a staging
    directory, as pacman does, and moves each file into `directory` when its
    last chunk arrives. What is unfinished goes when the `with` block ends."""

    def __init__(self, directory: str, sizes_bytes: Dict[str, int]) -> None:
        self.directory = directory
        self.sizes_bytes = sizes_bytes
        self.handles: Dict[str, int] = {}
        self.chunks_done: Dict[str, Set[int]] = {}
        self.end_bytes: Dict[str, int] = {}
        self.complete: List[str] = []
        # Bytes of the job written, each chunk counted once.
        self.written_bytes = 0
        self.chunk_end_bytes: Dict[Chunk, int] = {}

    def __enter__(self) -> Output:
        self.staging = tempfile.mkdtemp(prefix="download-", dir=self.directory)
        return self

    def __exit__(self, *exc_info: object) -> None:
        for handle in self.handles.values():
            os.close(handle)
        shutil.rmtree(self.staging)

    def write(self, chunk: Chunk, offset_bytes: int, data: bytes) -> None:
        handle = self.handles.get(chunk.path)
        if handle is None:
            name = os.path.join(self.staging, os.path.basename(chunk.path))
            handle = os.open(name, os.O_WRONLY | os.O_CREAT, 0o644)
            # Allocate the whole file up front. The first write usually lands
            # in the middle, and a sparse file ends up badly fragmented.
            try:
                os.posix_fallocate(handle, 0, self.sizes_bytes.get(chunk.path, 1))
            except OSError:
                pass
            self.handles[chunk.path] = handle
        at_bytes = (chunk.offset_bytes or 0) + offset_bytes
        os.pwrite(handle, data, at_bytes)
        before_bytes = self.chunk_end_bytes.get(chunk, 0)
        self.chunk_end_bytes[chunk] = max(before_bytes, offset_bytes + len(data))
        self.written_bytes += self.chunk_end_bytes[chunk] - before_bytes
        end_byte = max(self.end_bytes.get(chunk.path, 0), at_bytes + len(data))
        self.end_bytes[chunk.path] = end_byte

    def chunk_done(self, chunk: Chunk) -> None:
        done = self.chunks_done.setdefault(chunk.path, set())
        done.add(chunk.offset_bytes or 0)
        # A file we requested whole is one chunk, whatever its size.
        n_chunks = len(split_file(chunk.path, self.sizes_bytes.get(chunk.path, 0)))
        if chunk.offset_bytes is not None and len(done) < n_chunks:
            return
        handle = self.handles.pop(chunk.path, None)
        if handle is not None:
            # Truncate to what arrived: for a signature the allocated size was
            # a guess, and pacman rejects a signature with trailing zeros.
            os.ftruncate(handle, self.end_bytes.get(chunk.path, 0))
            os.close(handle)
        name = os.path.basename(chunk.path)
        os.replace(os.path.join(self.staging, name), os.path.join(self.directory, name))
        self.complete.append(chunk.path)


class Sample(NamedTuple):
    """Seconds since the connection started, bytes received on it by then,
    and the fields of TCP_INFO_OFFSETS then, if the kernel gave them."""

    t_sec: float
    received_bytes: int
    tcp: Optional[Dict[str, int]]


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id             INTEGER PRIMARY KEY,
    started_at     TEXT NOT NULL,     -- when the run started, UTC
    machine        TEXT NOT NULL,     -- the computer that ran it
    status_json    TEXT,              -- the mirror status as we fetched it
    draws_json     TEXT,              -- the run's draw of each mirror, bytes/s
    jobs_text      TEXT               -- the job list as pacman printed it
);

CREATE TABLE IF NOT EXISTS connections (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions (id),
    mirror         TEXT NOT NULL,
    address        TEXT,              -- the IP address we connected to
    started_at     TEXT NOT NULL,     -- when we started connecting, UTC
    connected_sec  REAL,              -- TLS handshake done; NULL if it failed
    error          TEXT               -- why connecting failed
);

-- All *_sec and t_sec values count from the connection's started_at. The
-- databases are the transfers whose path ends in .db.
CREATE TABLE IF NOT EXISTS transfers (
    id             INTEGER PRIMARY KEY,
    connection_id  INTEGER NOT NULL REFERENCES connections (id),
    path           TEXT NOT NULL,     -- relative to the mirror's url
    offset_bytes   INTEGER,           -- where the range starts; NULL for all
    size_bytes     INTEGER,           -- bytes expected; NULL if unknown
    sent_sec       REAL NOT NULL,
    headers_sec    REAL,
    finished_sec   REAL NOT NULL,
    status         INTEGER,
    received_bytes INTEGER NOT NULL,  -- of the body
    error          TEXT               -- NULL if the body arrived whole
);

-- Every SAMPLE_BYTES on a connection: the bytes so far, and what the kernel
-- reported (TCP_INFO_OFFSETS); ooo_packets counts the data segments that
-- arrived out of order. NULL where the kernel gave nothing.
CREATE TABLE IF NOT EXISTS samples (
    transfer_id     INTEGER NOT NULL REFERENCES transfers (id),
    t_sec           REAL NOT NULL,
    received_bytes  INTEGER NOT NULL,
    rtt_us          INTEGER,
    min_rtt_us      INTEGER,
    rcv_rtt_us      INTEGER,
    rcv_space_bytes INTEGER,
    data_segs_in    INTEGER,
    ooo_packets     INTEGER
);

CREATE INDEX IF NOT EXISTS samples_transfer ON samples (transfer_id);

-- A ball per mirror and run, what Speeds learns from: the bytes/s its lane
-- delivered from its first byte of the job to its last, and the run's
-- ceiling, its highest total over READING_SEC.
CREATE TABLE IF NOT EXISTS balls (
    session_id     INTEGER NOT NULL REFERENCES sessions (id),
    mirror         TEXT NOT NULL,
    bps            REAL NOT NULL,
    ceiling_bps    REAL NOT NULL
);
"""


class Log:
    """The SQLite file that holds every transfer of every run."""

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.session_id = 0

    def insert(self, table: str, **row: Any) -> int:
        """Insert a row; the next `db.commit()` stores it."""
        columns, values = ", ".join(row), ", ".join("?" * len(row))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({values})"
        rowid = self.db.execute(sql, tuple(row.values())).lastrowid
        assert rowid is not None
        return rowid

    def record(self, samples: List[Sample], **transfer: Any) -> None:
        """Insert a transfer and its samples."""
        transfer_id = self.insert("transfers", **transfer)
        values = ", ".join("?" * (3 + len(TCP_INFO_OFFSETS)))
        self.db.executemany(
            f"INSERT INTO samples VALUES ({values})",
            [
                (transfer_id, s.t_sec, s.received_bytes)
                + tuple((s.tcp or {}).get(k) for k in TCP_INFO_OFFSETS)
                for s in samples
            ],
        )

    def start_session(
        self, started: datetime, status_json: str, draws_bps: Dict[str, float]
    ) -> None:
        draws = {h: None if math.isinf(d) else round(d) for h, d in draws_bps.items()}
        self.session_id = self.insert(
            "sessions",
            started_at=iso(started),
            machine=socket.gethostname(),
            status_json=status_json,
            draws_json=json.dumps(draws),
        )
        self.db.commit()

    def set_jobs(self, jobs_text: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE sessions SET jobs_text = ? WHERE id = ?",
                (jobs_text, self.session_id),
            )

    def unusable(self, now: datetime) -> Set[str]:
        """Mirrors that in the last day served no file (they had the databases
        but not the packages), redirected, or ignored a range request."""
        rows = self.db.execute(
            "SELECT c.mirror FROM transfers t"
            " JOIN connections c ON t.connection_id = c.id"
            " WHERE c.started_at > ? GROUP BY c.mirror"
            " HAVING sum(t.status IN (200, 206)) = 0"
            " OR sum(t.status BETWEEN 300 AND 399) > 0"
            " OR sum(t.status = 200 AND t.offset_bytes IS NOT NULL) > 0",
            (iso(now - timedelta(days=1)),),
        )
        return {host for (host,) in rows}

    def recently_used(self, now: datetime) -> Set[str]:
        rows = self.db.execute(
            "SELECT mirror FROM connections GROUP BY mirror HAVING max(started_at) > ?",
            (iso(now - timedelta(seconds=COOLDOWN_SEC)),),
        )
        return {host for (host,) in rows}

    def balls(self) -> Dict[str, List[Ball]]:
        balls: Dict[str, List[Ball]] = {}
        for mirror, *ball in self.db.execute(
            "SELECT mirror, bps, ceiling_bps FROM balls"
        ):
            balls.setdefault(mirror, []).append(Ball(*ball))
        return balls


class Ball(NamedTuple):
    """What a mirror delivered in one run, and the run's ceiling, the highest
    total it reached."""

    bps: float
    ceiling_bps: float


class Speeds:
    """
    What we believe of each mirror's rate, as a normal in log. A ball, as a
    fraction of its run's ceiling, is in log the mirror's level plus noise.
    The levels are normal around the crowd's, so each is shrunk toward it by
    how much they spread and how noisy a ball is; the two variances are
    those of the fitted levels and of the balls around them, each with the
    seeded value counted once, as one more mirror or ball. All of it takes
    SPEED_ROUNDS rounds. A mirror's rate is its level at the median ceiling,
    and its spread is the uncertainty of its level.

    A lane that joins a full link keeps a small share of it, so its ball
    would say little of its mirror; but a lane opens only when the link has
    room, so hardly any ball is taken that way.
    """

    def __init__(self, balls: Dict[str, List[Ball]]) -> None:
        self.balls = balls
        seen = {
            h: [math.log(b.bps / b.ceiling_bps) for b in bs if b.bps and b.ceiling_bps]
            for h, bs in balls.items()
        }
        seen = {h: x for h, x in seen.items() if x}
        self.scale = math.log(
            statistics.median(b.ceiling_bps for bs in balls.values() for b in bs)
            if seen
            else 1.0
        )
        self.level: Dict[str, float] = {}
        self.crowd, self.spread, self.noise = SEEDED_LEVEL, SEEDED_SPREAD, SEEDED_NOISE
        self.seen = seen
        for _ in range(SPEED_ROUNDS if seen else 0):
            ratio = (self.noise / self.spread) ** 2
            for h, xs in seen.items():
                self.level[h] = (sum(xs) + ratio * self.crowd) / (len(xs) + ratio)
            self.crowd = statistics.fmean(self.level.values())
            spread = [(a - self.crowd) ** 2 for a in self.level.values()]
            self.spread = math.sqrt(
                (sum(spread) + SEEDED_SPREAD**2) / (len(spread) + 1)
            )
            misses = [(x - self.level[h]) ** 2 for h, xs in seen.items() for x in xs]
            self.noise = math.sqrt((sum(misses) + SEEDED_NOISE**2) / (len(misses) + 1))

    def mean_sd(self, host: str) -> tuple[float, float]:
        """The mirror's log rate: its level's estimate and spread."""
        n = len(self.seen.get(host, []))
        sd = 1 / math.sqrt(n / self.noise**2 + 1 / self.spread**2)
        return self.level.get(host, self.crowd) + self.scale, sd

    def draw_bps(self, host: str) -> float:
        """One rate the mirror might have today. With no ball of any mirror
        it might have any, so every mirror is worth a lane."""
        if not self.seen:
            return math.inf
        return math.exp(random.gauss(*self.mean_sd(host)))


# Our own HTTP/1.1 client pipelines: it sends the next request before the last
# response has arrived, so a connection never idles for a round trip between
# files. No redirects, compression or chunked encoding: mirrors need none.


def request_bytes(host: str, path: str, chunk: Chunk) -> bytes:
    byte_range = ""
    if chunk.offset_bytes is not None:
        byte_range = f"Range: bytes={chunk.offset_bytes}-{chunk.offset_bytes + chunk.size_bytes - 1}\r\n"
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"Accept-Encoding: identity\r\n"
        f"{byte_range}\r\n"
    ).encode()


async def read_head(reader: asyncio.StreamReader) -> tuple[int, Dict[str, str]]:
    """Read a status line and headers; return the status and the headers."""
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), STALL_SEC)
    lines = raw.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise OSError(f"not an HTTP response: {lines[0]!r}")
    headers = {}
    for line in lines[1:]:
        name, colon, value = line.partition(":")
        if colon:
            headers[name.strip().lower()] = value.strip()
    return int(parts[1]), headers


# We cache DNS lookups for the whole run: we want to measure the mirror, not
# our resolver. A lost DNS query once delayed a download by six seconds.
_addresses: Dict[tuple[str, int], List[Any]] = {}


async def resolve(host: str, port: int) -> List[Any]:
    if (host, port) not in _addresses:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        _addresses[host, port] = [addr for _, _, _, _, addr in infos]
    return _addresses[host, port]


class Connection:
    """A lane: a keep-alive TLS connection to one mirror. The controller sends
    requests, `run` reads the responses in order, and a connection the mirror
    closes after delivering, as nginx does after 100 requests, is replaced."""

    def __init__(self, mirror: Mirror, log: Log, screen: Screen) -> None:
        self.mirror, self.host, self.log = mirror, mirror.hostname(), log
        # Some mirrors serve from a path, like https://ftp.fau.de/archlinux/.
        self.base_path = urlparse(mirror.url).path.rstrip("/") + "/"
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.id = 0
        # Why connecting failed, and why we stopped the lane.
        self.error: Optional[str] = None
        self.stop_error: Optional[str] = None
        # Requests sent and not yet delivered, with when we sent them, and those
        # the mirror refused: one synced an hour ago lacks the newest packages.
        self.pending: List[tuple[Chunk, float]] = []
        self.failed: Set[Chunk] = set()
        self.pool: List[Chunk] = []
        self.out = Output("", {})
        # The status and error of every response, by the socket it came on.
        self.results: List[tuple[int, Optional[int], Optional[str]]] = []
        # Whether the controller may send requests, and when the lane began.
        self.ready = False
        self.lane_sec = time.monotonic()
        # The samples of the response being read, and the lane's rate.
        self.samples: List[Sample] = []
        self.rate = Rate(READING_SEC)
        # How long the first request took, from sending it to its headers: a
        # round trip and the mirror's time to start a response.
        self.request_sec = 0.0
        # What the screen shows: what the lane does, and the bytes it received
        # and their rate.
        self.status = ""
        self.shown_bytes = 0
        self.shown = Rate(SHOWN_RATE_SEC)
        self.shown_bps: Optional[float] = None
        screen.add(self)

    async def open(self) -> bool:
        """Connect, and record the attempt in the log."""
        started_at = now_iso()
        self.started_sec = time.monotonic()
        self.received_bytes = 0
        self.next_sample_bytes = SAMPLE_BYTES
        # Bytes requested and not yet received.
        self.outstanding_bytes = 0
        # Whether the connection is unusable (a read failed, we stopped reading
        # mid-response, or the mirror closed it), and whether the mirror did.
        self.aborted = self.closed_by_mirror = False
        address: Optional[str] = None
        context = ssl.create_default_context()
        try:
            for addr in await resolve(self.host, self.mirror.port()):
                connecting = asyncio.open_connection(
                    addr[0], addr[1], ssl=context, server_hostname=self.host
                )
                try:
                    self.reader, self.writer = await asyncio.wait_for(
                        connecting, CONNECT_TIMEOUT_SEC
                    )
                    address = addr[0]
                    break
                except OSError as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
            if self.writer is None:
                raise OSError(self.error or f"no address for {self.host}")
            self.error = None
        except NETWORK_ERRORS as exc:
            self.error = self.error or f"{type(exc).__name__}: {exc}"
        connected_sec = None if self.error else time.monotonic() - self.started_sec
        self.id = self.log.insert(
            "connections",
            session_id=self.log.session_id,
            mirror=self.host,
            address=address,
            started_at=started_at,
            connected_sec=connected_sec,
            error=self.error,
        )
        return self.error is None

    async def close(self) -> None:
        """Close the connection for the rest of the run."""
        await self.disconnect()
        if self.status != "error":
            self.status = "done"

    async def disconnect(self) -> None:
        """Close the socket. One we gave up on we abort: a mirror that has
        stalled does not answer a TLS close either, for 30 s."""
        if self.writer is not None and self.aborted:
            self.writer.transport.abort()
        elif self.writer is not None:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
        self.reader, self.writer = None, None

    def tcp_info(self) -> Optional[Dict[str, int]]:
        """The fields of TCP_INFO_OFFSETS as the kernel reports them for our
        socket, which needs no privileges, or None if it cannot."""
        if self.writer is None:
            return None
        try:
            sock = self.writer.get_extra_info("socket")
            raw = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 256)
            return {
                k: struct.unpack_from("I", raw, o)[0]
                for k, o in TCP_INFO_OFFSETS.items()
            }
        except (AttributeError, OSError, struct.error):
            return None

    def take_sample(self) -> None:
        t_sec = time.monotonic() - self.started_sec
        self.samples.append(Sample(t_sec, self.received_bytes, self.tcp_info()))
        self.next_sample_bytes += SAMPLE_BYTES

    def send_request(self, chunk: Chunk) -> None:
        assert self.writer is not None
        path = self.base_path + chunk.path
        # On a connection the mirror closed, requests wait to be handed back.
        if not self.writer.transport.is_closing():
            self.writer.write(request_bytes(self.host, path, chunk))
        self.pending.append((chunk, time.monotonic() - self.started_sec))
        self.outstanding_bytes += chunk.size_bytes

    def stop(self, why: str) -> None:
        """End the lane. The response being read is cut off, and what the
        lane holds goes back to the pool."""
        self.stop_error, self.ready = why, False

    async def read_body(self, length_bytes: int, chunk: Chunk, save: bool) -> None:
        """Read a body, into the output if `save`, until it is whole or the
        lane is stopped."""
        assert self.reader is not None
        read_bytes = 0
        while read_bytes < length_bytes:
            data = await asyncio.wait_for(
                self.reader.read(min(length_bytes - read_bytes, READ_BYTES)),
                STALL_SEC,
            )
            if not data:
                raise OSError("connection closed mid body")
            if save:
                self.out.write(chunk, read_bytes, data)
            read_bytes += len(data)
            self.received_bytes += len(data)
            self.shown_bytes += len(data)
            self.outstanding_bytes -= len(data)
            if self.received_bytes >= self.next_sample_bytes:
                self.take_sample()
            if self.stop_error is not None:
                self.aborted = True
                return

    async def read_response(self) -> None:
        """Read and record the response to the oldest pending request, which
        stays pending unless it arrived whole or the mirror refused it."""
        assert self.reader is not None
        chunk, sent_sec = self.pending[0]
        self.samples = []
        before_bytes = self.received_bytes
        status: Optional[int] = None
        headers_sec: Optional[float] = None
        error: Optional[str] = None
        try:
            status, headers = await read_head(self.reader)
            headers_sec = time.monotonic() - self.started_sec
            self.request_sec = self.request_sec or headers_sec - sent_sec
            if chunk.offset_bytes is not None and status == 200:
                error = "whole file sent for a range request"
                self.aborted = True
            elif "content-length" not in headers:
                error = "response without a length"
                self.aborted = True
            else:
                ok = status in (200, 206)
                if ok and chunk.offset_bytes is None:
                    # The size of a whole file, which we may have estimated.
                    self.out.sizes_bytes[chunk.path] = int(headers["content-length"])
                await self.read_body(int(headers["content-length"]), chunk, ok)
                if self.aborted:
                    error = self.stop_error
                elif not ok:
                    error = f"HTTP {status}"
                # The response is whole, but nothing more will come.
                if headers.get("connection", "").lower() == "close":
                    self.aborted = self.closed_by_mirror = True
        except TimeoutError:
            error = f"nothing for {STALL_SEC:.0f} s"
            self.aborted = True
        except NETWORK_ERRORS as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.aborted = self.closed_by_mirror = True

        body_bytes = self.received_bytes - before_bytes
        self.outstanding_bytes -= chunk.size_bytes - body_bytes
        if error is None:
            self.pending.pop(0)
            self.out.chunk_done(chunk)
        elif status not in (None, 200, 206):
            self.pending.pop(0)
            self.failed.add(chunk)
            self.pool.insert(0, chunk)
        self.results.append((self.id, status, error))
        self.log.record(
            self.samples,
            connection_id=self.id,
            path=chunk.path,
            offset_bytes=chunk.offset_bytes,
            size_bytes=chunk.size_bytes or None,
            sent_sec=sent_sec,
            headers_sec=headers_sec,
            finished_sec=time.monotonic() - self.started_sec,
            status=status,
            received_bytes=body_bytes,
            error=error,
        )

    async def run(
        self,
        out: Output,
        pool: List[Chunk],
        refill: Optional[Callable[[], None]] = None,
    ) -> None:
        """Download into `out` until the lane is stopped or fails, or with
        `refill`, which sends the requests, until nothing is pending. What did
        not arrive goes to the front of `pool`, as its files are started."""
        self.out, self.pool = out, pool
        while self.stop_error is None:
            if self.writer is None and not await self.open():
                break
            self.ready = True
            if refill is not None:
                refill()
            if not self.pending:
                if refill is not None:
                    break
                await asyncio.sleep(TICK_SEC)
                continue
            await self.read_response()
            if self.aborted:
                # Hand back what did not arrive before anything else runs, or
                # a lane waiting for it may see this one stopped and stop too.
                self.ready = False
                pool[:0] = [chunk for chunk, _ in self.pending]
                self.pending = []
                delivered = self.received_bytes > 0
                await self.disconnect()
                if not (self.closed_by_mirror and delivered):
                    break
        self.ready = False
        pool[:0] = [chunk for chunk, _ in self.pending]
        self.pending = []
        self.status = "error" if self.broken() else "idle"

    def broken(self) -> bool:
        """Whether the lane failed: its connection did, other than when we
        stopped it, or the mirror refused most requests (lacking a few files
        is fine)."""
        refused = sum(status not in (None, 200, 206) for _, status, _ in self.results)
        broke = any(
            status in (None, 200, 206) and error not in (None, self.stop_error)
            for _, status, error in self.results[-1:]
        )
        return bool(self.error or broke or 2 * refused > len(self.results))

    def note(self) -> str:
        """How many requests failed on the socket and the most common reason,
        or why it failed, or why we stopped it; without the exception's name
        and number, which the log has."""
        errors = [e for c, _, e in self.results if c == self.id and e]
        failed = [e for e in errors if e != self.stop_error]
        if failed:
            return (
                f"{len(failed)} failed: " + statistics.mode(failed).rpartition("] ")[2]
            )
        return (self.error or "".join(errors[-1:])).rpartition("] ")[2]


async def refresh_databases(
    log: Log, screen: Screen, mirrors: List[Mirror], sync_dir: str
) -> Optional[Connection]:
    """Download all databases from the first mirror that delivers them, so
    that they match, and return its connection, open for the first lane. The
    largest goes first, so that its header makes the total almost exact."""
    arch = pacman_conf("Architecture")[0]
    sizes_bytes = {}
    for repo in pacman_conf("--repo-list"):
        old = os.path.join(sync_dir, f"{repo}.db")
        size_bytes = os.path.getsize(old) if os.path.exists(old) else 0
        sizes_bytes[f"{repo}/os/{arch}/{repo}.db"] = size_bytes
    for mirror in mirrors:
        conn = Connection(mirror, log, screen)
        requests = [Chunk(path, size) for path, size in sizes_bytes.items()]
        requests.sort(key=lambda c: -c.size_bytes)

        def send_all() -> None:
            while requests:
                conn.send_request(requests.pop(0))

        conn.status = "sync"
        with Output(sync_dir, sizes_bytes) as out:
            screen.show_job(out, "databases")
            await conn.run(out, requests, send_all)
        log.db.commit()
        if len(out.complete) == len(sizes_bytes):
            return conn
        await conn.close()
    return None


def assign(pool: List[Chunk], conns: List[Connection]) -> None:
    """Keep REQUESTED_SEC of work at every lane. A lane with nothing to do
    gets the next chunk it has not refused before anything else, so that no
    lane idles and a rate counts no idle time. Then, while a lane has less,
    send the next chunk to the lane that would finish it first of those that
    have less, counting per request the time the first one took (some
    mirrors take 16 ms per response even when pipelined). So each lane gets
    work at the rate it delivers, and what a lane cannot deliver in time the
    controller takes back. A lane without a rate counts as busy once it has
    a request."""

    def work_sec(c: Connection, chunk: Optional[Chunk] = None) -> float:
        rate_bps = c.rate.bps()
        if not rate_bps:
            return math.inf if c.pending or chunk else 0.0
        size_bytes = c.outstanding_bytes + (chunk.size_bytes if chunk else 0)
        return size_bytes / rate_bps + (len(c.pending) + bool(chunk)) * c.request_sec

    # A connection still opening has no work, so it would win every chunk.
    ready = [c for c in conns if c.ready]
    for c in ready:
        chunk = next((k for k in pool if k not in c.failed), None)
        if not c.pending and chunk is not None:
            pool.remove(chunk)
            c.send_request(chunk)
    for chunk in list(pool):
        short = [c for c in ready if work_sec(c) < REQUESTED_SEC]
        if not short:
            return
        able = [c for c in short if chunk not in c.failed]
        if able:
            pool.remove(chunk)
            min(able, key=lambda c: work_sec(c, chunk)).send_request(chunk)


async def download(
    log: Log,
    screen: Screen,
    mirrors: Dict[str, Mirror],
    draws_bps: Dict[str, float],
    pool: List[Chunk],
    out: Output,
    first: Optional[Connection],
) -> None:
    """
    Download the pool over lanes. Every TICK_SEC: hand out work, end a lane
    that holds more than it can deliver in time, and open a lane on the next
    mirror in the draws while the link has room and that would make the rest
    of the job take RAMP_SEC + MIRROR_SEC less at the lanes' total plus the
    mirror's draw. A lane's effect shows only after RAMP_SEC + READING_SEC,
    so after one opens the next waits that long; the second opens at once,
    as one lane alone tells nothing about the link. A mirror whose lane
    failed gets no other in this run.
    """
    rates_bps = dict(draws_bps)
    candidates = [h for h in draws_bps if first is None or h != first.host]
    lanes: Dict[Connection, asyncio.Task[None]] = {}
    # One connection per mirror: a mirror that gave its requests away keeps
    # its line if it gets another lane.
    made = {first.host: first} if first is not None else {}
    job_bytes = sum(out.sizes_bytes.values())

    def received_bytes() -> int:
        return sum(c.shown_bytes for c in made.values())

    total = Rate(READING_SEC, received_bytes())
    ceiling_bps = 0.0
    # When the last lane opened; each lane's bytes at the last tick, and when
    # it first received since it opened.
    opened_sec = -math.inf
    seen: Dict[Connection, int] = {}
    receiving: Dict[Connection, float] = {}
    # For each mirror's ball: when it first received and its bytes then, and
    # when it last received.
    began: Dict[Connection, tuple[float, int]] = {}
    last_sec: Dict[Connection, float] = {}

    def open_lane(host: str) -> None:
        nonlocal opened_sec
        conn = made.get(host) or Connection(mirrors[host], log, screen)
        made[host], conn.stop_error, conn.lane_sec = conn, None, time.monotonic()
        # The rate goes on from before: a lane's rate counts only once it has
        # received for READING_SEC anyway.
        conn.status = "download"
        lanes[conn] = asyncio.create_task(conn.run(out, pool))
        receiving.pop(conn, None)
        seen[conn], opened_sec = conn.shown_bytes, conn.lane_sec

    if first is not None:
        open_lane(first.host)
    while True:
        now_sec = time.monotonic()
        for conn in lanes:
            conn.rate.update(conn.shown_bytes)
        ceiling_bps = max(ceiling_bps, total.update(received_bytes()))
        # The link has room unless the two lanes that deliver most both queue
        # (see QUEUE_FULL_SEC); with fewer delivering, a second opens to read
        # it. An idle lane's round trip is that of its last request.
        delivering = sorted(lanes, key=lambda c: -c.rate.bps())[:2]
        queues = [c.tcp_info() for c in delivering if c.rate.bps()]
        room = len(queues) < 2 or any(
            not t or t["rtt_us"] - t["min_rtt_us"] < QUEUE_FULL_SEC * 1e6
            for t in queues
        )
        for conn in lanes:
            got_bytes, seen[conn] = conn.shown_bytes - seen[conn], conn.shown_bytes
            if got_bytes:
                receiving.setdefault(conn, now_sec)
                began.setdefault(conn, (now_sec, conn.shown_bytes))
                last_sec[conn] = now_sec
        for conn in [c for c, task in lanes.items() if task.done()]:
            lanes.pop(conn).result()
            log.db.commit()
            if conn.stop_error == TOO_SLOW:
                rates_bps[conn.host] = conn.rate.bps()
                candidates.append(conn.host)
            await conn.close()
        live = list(lanes)
        if not pool and not any(c.pending for c in live):
            break
        assign(pool, live)

        # A lane ends when what it holds would take longer than the rest of the
        # job at the other lanes' rates, plus the cost of the change: what
        # arrived of the current response is lost, and the others ask again.
        # Its rate counts once it has received for READING_SEC; connecting
        # and the first round trip are no measure of it.
        able = [c for c in live if c.pending or any(k not in c.failed for k in pool)]
        lane_bps = {c: c.rate.bps() for c in able}
        left_bytes = max(0, job_bytes - out.written_bytes)
        for c, rate_bps in lane_bps.items():
            others_bps = sum(lane_bps.values()) - rate_bps
            measured = now_sec - receiving.get(c, now_sec) >= READING_SEC
            if measured and rate_bps and others_bps:
                if c.outstanding_bytes / rate_bps > RAMP_SEC + left_bytes / others_bps:
                    c.stop(TOO_SLOW)

        if not able and not (candidates and pool):
            # Nothing can make progress; pacman downloads what is left.
            break
        since_sec = now_sec - opened_sec
        if candidates and pool and room and settled(len(lanes), since_sec):
            host = max(candidates, key=lambda h: rates_bps[h])
            lanes_bps = sum(lane_bps.values())
            if saves_enough(left_bytes, lanes_bps, rates_bps[host]):
                candidates.remove(host)
                open_lane(host)
        await asyncio.sleep(TICK_SEC)

    for conn, task in lanes.items():
        conn.stop(JOB_DONE)
        await task
        await conn.close()
    for conn, (first_sec, first_bytes) in began.items():
        if last_sec[conn] - first_sec >= READING_SEC:
            got_bps = (conn.shown_bytes - first_bytes) / (last_sec[conn] - first_sec)
            log.insert(
                "balls",
                session_id=log.session_id,
                mirror=conn.host,
                bps=got_bps,
                ceiling_bps=ceiling_bps,
            )
    log.db.commit()


def refresh_order(speeds: Speeds, draws_bps: Dict[str, float]) -> List[str]:
    """The order in which mirrors are asked for the databases, which the
    rest of the run waits for: first those in the draws that we believe
    deliver at least REFRESH_SHARE of the best one's rate, so that no crawler
    holds up the run; not the best alone, as the mirror that refreshes opens
    the first lane and reads higher than lanes that share the link, and
    would keep the refresh for good."""
    best = max(speeds.mean_sd(h)[0] for h in draws_bps)
    order = [
        h for h in draws_bps if speeds.mean_sd(h)[0] >= best + math.log(REFRESH_SHARE)
    ]
    return order + [h for h in draws_bps if h not in order]


def write_mirrorlist(path: str, by_host: Dict[str, Mirror], log: Log) -> None:
    """Write the N_MIRRORLIST mirrors with the best rate in nine runs out of
    ten, as the log rates them now, in the format of pacman's mirrorlist.
    pacman cannot leave a mirror that turns out slow halfway, as our lanes
    do, so a mirror's rate in its bad runs counts, not its median."""
    speeds = Speeds(log.balls())
    rates_bps = {}
    for host in by_host:
        mean, sd = speeds.mean_sd(host)
        one_run = statistics.NormalDist(mean, math.hypot(sd, speeds.noise))
        rates_bps[host] = math.exp(one_run.inv_cdf(0.1))
    lines = [f"# Written by mirrorlist_v5.py at {now_iso()}, best first."]
    for host in sorted(rates_bps, key=lambda h: -rates_bps[h])[:N_MIRRORLIST]:
        lines.append(f"# p10 rate >= {rates_bps[host] / 1e6:.1f} MB/s")
        lines.append(f"Server = {by_host[host].url.rstrip('/')}/$repo/os/$arch")
    with open(path + ".part", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(path + ".part", path)


def settled(n_lanes: int, since_sec: float) -> bool:
    """Whether the lanes show what the last one did: it opened RAMP_SEC +
    READING_SEC ago. The second lane need not wait, as one lane alone tells
    nothing about the link."""
    return n_lanes < 2 or since_sec >= RAMP_SEC + READING_SEC


def saves_enough(left_bytes: float, lanes_bps: float, lane_bps: float) -> bool:
    """Whether a new lane at lane_bps beside lanes at lanes_bps would make
    the rest of the job take more than RAMP_SEC + MIRROR_SEC less."""
    if not lanes_bps:
        return True
    saved_sec = left_bytes / lanes_bps - left_bytes / (lanes_bps + lane_bps)
    return saved_sec > RAMP_SEC + MIRROR_SEC


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def pacman_conf(*args: str) -> List[str]:
    return command("pacman-conf", *args).split()


def pacman_jobs(db_path: str, out: str) -> str:
    """What pacman would download, comparing the installed packages in
    `db_path`/local with the databases in `db_path`/sync, and skipping files in
    `out` or in its own cache. `--print` needs no root and takes no lock."""
    caches = [out] + pacman_conf("CacheDir")
    args = [f"--cachedir={cache}" for cache in caches] + ["--dbpath", db_path]
    return command("pacman", "-Sup", *args, "--print-format", "%r %n %v %s %f %l")


def job_files(text: str, arch: str) -> Dict[str, int]:
    """The path and size in bytes of every file to download, including signatures.
    Packages already in the cache have a file:// url."""
    sizes_bytes = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 6 and not parts[5].startswith("file://"):
            repo, _name, _version, size_bytes, filename, _url = parts
            sizes_bytes[f"{repo}/os/{arch}/{filename}"] = int(size_bytes)
            sizes_bytes[f"{repo}/os/{arch}/{filename}.sig"] = SIGNATURE_BYTES
    return sizes_bytes


def job_chunks(sizes_bytes: Dict[str, int]) -> List[Chunk]:
    """The chunks of the job: the largest files first, each in order, and the
    small files left to even out the lanes at the end; a signature after each
    full chunk, where a mirror slow to start responses loses nothing."""
    paths = sorted(sizes_bytes, key=lambda path: -sizes_bytes[path])
    signatures = [Chunk(p, sizes_bytes[p]) for p in paths if p.endswith(".sig")]
    chunks = []
    for path in (p for p in paths if not p.endswith(".sig")):
        for chunk in split_file(path, sizes_bytes[path]):
            chunks.append(chunk)
            if chunk.size_bytes == CHUNK_BYTES and signatures:
                chunks.append(signatures.pop(0))
    return chunks + signatures


def count_files(paths: Iterable[str]) -> int:
    """The paths that are packages or databases, not signatures."""
    return sum(not path.endswith(".sig") for path in paths)


class Rate:
    """The bytes of the last `window_sec` over that time, or over the time
    since the rate began if that is shorter, from the running total of
    bytes at each update."""

    def __init__(self, window_sec: float, total_bytes: int = 0) -> None:
        self.window_sec = window_sec
        self.history = collections.deque([(time.monotonic(), total_bytes)])

    def update(self, total_bytes: int) -> float:
        now_sec = time.monotonic()
        self.history.append((now_sec, total_bytes))
        while self.history[1][0] <= now_sec - self.window_sec:
            self.history.popleft()
        return self.bps()

    def bps(self) -> float:
        (first_sec, first_bytes), (last_sec, last_bytes) = (
            self.history[0],
            self.history[-1],
        )
        return (
            (last_bytes - first_bytes) / (last_sec - first_sec)
            if last_sec > first_sec
            else 0.0
        )


class Screen:
    """What the user sees: a line per mirror, in the order we first connected
    to it, and the job's progress below, redrawn every REDRAW_SEC on a
    terminal. Anywhere else the lines are printed once, at the end."""

    def __init__(self, hosts: List[str]) -> None:
        self.host_width = max(map(len, hosts), default=0)
        self.terminal = sys.stdout.isatty()
        self.conns: Dict[str, Connection] = {}
        # How many lines the last redraw drew, which the next goes back over.
        self.n_drawn = 0
        self.job: Optional[Output] = None
        self.noun = ""
        self.job_rate = Rate(SHOWN_RATE_SEC)
        self.left_sec: Optional[float] = None
        self.left_at_sec = 0.0
        self.task = asyncio.create_task(self.keep_drawing())

    def add(self, conn: Connection) -> None:
        self.conns[conn.host] = conn

    def show_job(self, out: Output, noun: str) -> None:
        self.job, self.job_rate, self.noun = out, Rate(SHOWN_RATE_SEC), noun
        self.left_sec, self.left_at_sec = None, 0.0

    def close(self) -> None:
        """Print every line as it is, without the job's progress. The run is
        over, so no mirror waits for work any more."""
        self.task.cancel()
        self.job = None
        for c in self.conns.values():
            c.status = "done" if c.status == "idle" else c.status
        self.draw()
        if not self.terminal:
            print(*(self.row(c)[0] for c in self.conns.values()), sep="\n")

    async def keep_drawing(self) -> None:
        while True:
            self.draw()
            await asyncio.sleep(REDRAW_SEC)

    def draw(self) -> None:
        if not self.terminal:
            return
        width = shutil.get_terminal_size().columns - 1
        rows = [self.styled(c, width) for c in self.conns.values()]
        rows += self.progress(width)
        # To the start of the last redraw, and clear to the end of the screen.
        back = f"\x1b[{self.n_drawn}F\x1b[J" if self.n_drawn else ""
        sys.stdout.write(back + "".join(row + "\x1b[0m\n" for row in rows))
        sys.stdout.flush()
        self.n_drawn = len(rows)

    def styled(self, conn: Connection, width: int) -> str:
        """A line's row, cut to `width`, as a wider one would take two lines,
        and then colored, so that the cut cannot split a color code: a mirror
        in use bold up to its note, with its status in cyan, and a failed
        one's status in red."""
        row, note = self.row(conn)
        text, n_head = row[:width], len(row) - len(note)
        if conn.status in ("sync", "download"):
            return (
                f"\x1b[1;36m{text[:8]}\x1b[39m{text[8:n_head]}\x1b[22m{text[n_head:]}"
            )
        if conn.status == "error":
            return f"\x1b[31m{text[:8]}\x1b[39m{text[8:]}"
        return text

    def row(self, conn: Connection) -> tuple[str, str]:
        """A mirror's row, and the note it ends with."""
        # A mirror no longer in use keeps the rate it had when it last was,
        # so that the rate a lane ended at stays next to why it ended.
        if conn.status in ("sync", "download"):
            conn.shown_bps = conn.shown.update(conn.shown_bytes)
        note, rate = conn.note(), ""
        if conn.shown_bps is not None:
            rate = f"{conn.shown_bps / 1e6:5.1f} MB/s"
        head = f"{conn.status:>8} {conn.host:<{self.host_width}}  "
        numbers = f"{conn.shown_bytes / 1e6:6.1f} MB  {rate:>10}  "
        return (head + numbers + note).rstrip(), note

    def progress(self, width: int) -> List[str]:
        """The job's files and bytes so far, the rate, the time left at that
        rate, and a bar. Without an estimate of the size, nothing."""
        out = self.job
        total_bytes = sum(out.sizes_bytes.values()) if out else 0
        if out is None or not total_bytes:
            return []
        rate_bps = self.job_rate.update(out.written_bytes)
        status = (
            f"{out.written_bytes / 1e6:.0f} of {total_bytes / 1e6:.0f} MB, "
            f"{count_files(out.complete)} of {count_files(out.sizes_bytes)} "
            f"{self.noun}, {rate_bps / 1e6:.1f} MB/s"
        )
        # The time left is shown in seconds, so it changes once a second.
        now_sec = time.monotonic()
        if rate_bps > 0 and now_sec - self.left_at_sec >= 1.0:
            elapsed_sec, self.left_at_sec = now_sec - self.left_at_sec, now_sec
            estimate_sec = max(0, total_bytes - out.written_bytes) / rate_bps
            counted_sec = max(0.0, (self.left_sec or 0.0) - elapsed_sec)
            weight = 1 - math.exp(-elapsed_sec / SHOWN_LEFT_SEC)
            if self.left_sec is None:
                weight = 1.0
            self.left_sec = counted_sec + (estimate_sec - counted_sec) * weight
        if self.left_sec is not None:
            left_sec = round(self.left_sec)
            status += f", {left_sec // 60}:{left_sec % 60:02d} left"
        fraction = min(1.0, out.written_bytes / total_bytes)
        # The bar ends where the rates in the rows do: the host, and 32
        # characters of the other columns. It fits, so only the status is cut.
        n_bar = max(10, min(width, self.host_width + 32) - len("[] 100%"))
        filled = round(fraction * n_bar)
        dashes = "-" * (n_bar - filled)
        return [
            status[:width],
            f"[{'#' * filled}\x1b[2m{dashes}\x1b[22m] {fraction:4.0%}",
        ]


async def run(args: argparse.Namespace) -> int:
    log = Log(args.db)
    now = datetime.now(timezone.utc)

    # Read the log while the mirror status downloads. The sleep lets the task
    # start before the blocking reads.
    status_task = asyncio.create_task(get_mirrors())
    await asyncio.sleep(0)
    arch = pacman_conf("Architecture")[0]
    resting = set() if args.no_cooldown else log.recently_used(now)
    unusable = log.unusable(now)
    speeds = Speeds(log.balls())
    status_json, mirrors = await status_task

    mirrors = [m for m in filter_mirrors(mirrors, now) if m.hostname() not in unusable]
    by_host = {m.hostname(): m for m in mirrors}
    available = [h for h in by_host if h not in resting]
    if not available:
        print("No mirrors left to use.", file=sys.stderr)
        return 1

    # One draw per mirror for the run (Thompson sampling), so that a mirror
    # gets a lane with the chance that it is fast. Equal draws in random order.
    random.shuffle(available)
    draws = sorted(((speeds.draw_bps(h), h) for h in available), key=lambda d: -d[0])
    draws_bps = {h: d for d, h in draws}
    log.start_session(now, status_json, draws_bps)
    screen = Screen(list(by_host))
    # The connection that refreshes the databases opens the first lane; the
    # others follow the draws.
    order = refresh_order(speeds, draws_bps)
    sync_dir = os.path.join(args.db_path, "sync")
    mirrors = [by_host[h] for h in order]
    first = await refresh_databases(log, screen, mirrors, sync_dir)
    if first is None:
        screen.close()
        print("Could not refresh the databases.", file=sys.stderr)
        return 1
    # The mirrors that failed the refresh get no lane.
    for host in order[: order.index(first.host)]:
        del draws_bps[host]
    # Nothing is redrawn while pacman runs, so show the refresh complete.
    screen.draw()
    if args.jobs:
        jobs_text = sys.stdin.read() if args.jobs == "-" else open(args.jobs).read()
    else:
        jobs_text = pacman_jobs(args.db_path, args.out)
    log.set_jobs(jobs_text)

    sizes_bytes = job_files(jobs_text, arch)
    pool = job_chunks(sizes_bytes)
    if not pool:
        screen.close()
        write_mirrorlist(args.mirrorlist, by_host, log)
        print("Nothing to download.")
        return 0
    with Output(args.out, sizes_bytes) as out:
        screen.show_job(out, "packages")
        # The summary is of the packages alone: their bytes over the time
        # from the first request for them to the last byte.
        packages_sec = time.monotonic()
        await download(
            log,
            screen,
            by_host,
            draws_bps,
            pool,
            out,
            first,
        )
    screen.close()
    write_mirrorlist(args.mirrorlist, by_host, log)
    n_packages, n_got = count_files(sizes_bytes), count_files(out.complete)
    counted = f"{n_got}" if n_got == n_packages else f"{n_got} of {n_packages}"
    got_bytes = sum(out.end_bytes.get(path, 0) for path in out.complete)
    took_sec = time.monotonic() - packages_sec
    print(
        f"Done: {counted} packages, {got_bytes / 1e6:.0f} MB in {took_sec:.1f} s "
        f"({got_bytes / took_sec / 1e6:.1f} MB/s). Run pacman -Su to install."
    )
    missing = len(sizes_bytes) - len(out.complete)
    if missing:
        print(f"{missing} files did not arrive; pacman -Su will download them.")
    return 0


def cannot_create(directory: str) -> Optional[str]:
    """Why we cannot create a file in `directory`, or None. We try, because
    on the 9p share `os.access` says yes to root and then the host refuses."""
    try:
        fd, path = tempfile.mkstemp(dir=directory)
    except OSError as e:
        return e.strerror or str(e)
    os.close(fd)
    os.unlink(path)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db", default="mirrorlist_v5.sqlite", help="the log of every run"
    )
    parser.add_argument(
        "--jobs",
        help="a captured `pacman -Sup --print-format '%%r %%n %%v %%s %%f %%l'`, "
        "or - for stdin, instead of asking pacman after the refresh",
    )
    parser.add_argument(
        "--dir",
        help="put the packages here, the databases in its sync/ and the "
        "mirrorlist in it, instead of in pacman's own places, so that a test "
        "needs no root",
    )
    parser.add_argument("--no-cooldown", action="store_true")
    args = parser.parse_args()

    real_db_path = pacman_conf("DBPath")[0]
    if args.dir:
        # pacman compares the installed packages, in `local`, with the
        # databases in `sync`, so our database directory needs both.
        args.out = args.db_path = args.dir
        args.mirrorlist = os.path.join(args.dir, os.path.basename(MIRRORLIST_PATH))
        os.makedirs(os.path.join(args.dir, "sync"), exist_ok=True)
        local = os.path.join(args.dir, "local")
        if not os.path.lexists(local):
            os.symlink(os.path.join(real_db_path, "local"), local)
    else:
        args.out, args.db_path = pacman_conf("CacheDir")[0], real_db_path
        args.mirrorlist = MIRRORLIST_PATH

    # Check up front that we can write everywhere we need to, including next to
    # the log, where SQLite creates a journal file on every write.
    log_dir = os.path.dirname(os.path.abspath(args.db))
    writing = [args.out, log_dir, os.path.join(args.db_path, "sync")]
    writing.append(os.path.dirname(args.mirrorlist))
    for directory in writing:
        why = cannot_create(directory)
        if why is not None:
            print(f"Cannot write in {directory}: {why}.", file=sys.stderr)
            return 1
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
