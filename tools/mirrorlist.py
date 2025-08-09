#!/usr/bin/env python3

# mirrorlist.py -- Select the fastest Arch Linux Mirror
# Written in 2025 by Ruud van Asseldonk

# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

from __future__ import annotations

import heapq
import math
import random
import statistics
import time

import asyncio
import aiohttp  # Tested with 3.12.15

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientError

from typing import Dict, Iterable, Literal, List, NamedTuple, Set
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


class Mirror(NamedTuple):
    """
    The fields here map directly to those documented at
    <https://archlinux.org/mirrors/status/>.

    Aside from those, we add a few mutable list fields that record statistics
    about the mirror.
    """

    active: bool

    # Completion, not a percentage, but between 0.0 and 1.0.
    completion_pct: float

    # Country named and code, uppercase.
    country: str
    country_code: str

    # Average mirroring delay that the Arch mirror checker observed in seconds.
    delay: int

    # Duration and stddev of the duration that it took the Arch mirror checker
    # to retrieve the `lastsync` file, in seconds.
    duration_avg: float
    duration_stddev: float

    # Whether the mirror supports IPv4, IPv6, and hosts ISOs.
    ipv4: bool
    ipv6: bool
    isos: bool

    # Last time the mirror was synced, according to the Arch mirror checker.
    last_sync: str

    # Supported transport protocol.
    protocol: Literal["https"] | Literal["http"] | Literal["rsync"]

    # Score according to the Arch mirror checker's formula.
    score: float

    # Base repo URL, and details URL.
    url: str
    details: str

    def is_ok(self, country_codes: Set[str]) -> bool:
        """Return whether we want this mirror in our final list."""
        return (
            self.active
            and (self.protocol == "https")
            and (self.country_code in country_codes)
            and (self.completion_pct == 1.0)
        )

    def is_fresh(self, now: datetime) -> bool:
        assert datetime.tzinfo is not None
        dt = now - datetime.fromisoformat(self.last_sync)
        # We require that the mirror is less than an hour behind on average,
        # and that the last sync was less than 1.5 hours ago. Note, in practice
        # both rule out some mirrors, there are mirrors that are in sync on
        # average, but synced longer than 1.5h ago currently!
        return (self.delay < 3600) and (dt < timedelta(minutes=90))

    def hostname(self) -> str:
        h = urlparse(self.url).hostname
        assert h is not None, "Mirrors urls must have a hostname"
        return h


class Point(NamedTuple):
    """
    A measurement of retrieving a file from a server.
    """

    # Number of body bytes transferred.
    len: int

    # Duration in seconds.
    dt_sec: float


class MirrorStats:
    """
    A mirror, together with mutable statistics about it.
    """

    def __init__(self, mirror: Mirror) -> None:
        self.mirror = mirror

        # Response body sizes in bytes.
        self.lens: List[int] = []

        # Request durations in seconds.
        self.dt_secs: List[float] = []

        # Errors observed while measuring.
        self.errors: List[ClientError] = []

        # Download throughput in bytes per seconds.
        self.rate_bps = 0.0

        # Optimistic estimate of the throughput in bytes per second.
        self.rate_bps_upper = 1.0

    def refresh_stats(self) -> None:
        if len(self.dt_secs) < 2:
            return

        # Compute the average transfer rate, weighted by file size (because we
        # are interested in sustained transfer rate more than latency), over the
        # fastest half of the transfers. This ensures that the tiny files we
        # download at the start do not drag down the average as much.
        datas = sorted((dx / dt, dx, dt) for dx, dt in zip(self.lens, self.dt_secs))
        datas = datas[len(datas) // 2 :]
        self.rate_bps = sum(p[1] for p in datas) / sum(p[2] for p in datas)

        diffs = [(dx / dt) - self.rate_bps for dx, dt in zip(self.lens, self.dt_secs)]

        # For the upper bound, we compute the deviation of every sample from
        # the average rate, as an estimate of the variance. This is wildly
        # inaccurate, especially for the tiny files that have a much lower
        # throughput, but that is the point of it: we want wide error bars
        # with little data, and shrink them over time.
        diffs = [(dx / dt) - self.rate_bps for dx, dt in zip(self.lens, self.dt_secs)]
        variance = sum(d * d for d in diffs) / (len(diffs) - 1)

        # Before we download anything of serious size, the estimates are so
        # wildly misleading compared to when we do have those, that we need
        # to add a bonus to put them in the same scale, to make the priority
        # queue sorting work.
        bonus = 500.0e6 / math.sqrt(sum(self.lens))

        # TODO: Should we decay it with the number of data points once more?
        self.rate_bps_upper = (
            self.rate_bps + 25.0 * math.sqrt(variance) / len(diffs) + bonus
        )

    def __str__(self):
        m = self.mirror
        rate_mbps = self.rate_bps / 1e6
        rate_mbps_upper = self.rate_bps_upper / 1e6
        return (
            f"{m.country_code} mbps={rate_mbps:5.2f}..{rate_mbps_upper:5.2f} "
            f"n={len(self.dt_secs):>2} {m.hostname()}"
        )

    async def _fetch_file(self, http: ClientSession, url: str) -> None:
        """
        Fetch the file, and record how long that took in the stats.
        """
        t0 = time.monotonic()
        try:
            async with http.get(url) as r:
                data = await r.read()
                t1 = time.monotonic()
                r.raise_for_status()

                self.lens.append(len(data))
                self.dt_secs.append(t1 - t0)

        except ClientError as exc:
            self.errors.append(exc)

    async def fetch_file(self, http: ClientSession, kind: str) -> None:
        """Fetch a file and record the stats."""
        urls = {
            # A few bytes.
            "small": "lastsync",
            # About 120 kB.
            "medium": "core/os/x86_64/core.db",
            # About 1.4 MB.
            "large": "core/os/x86_64/core.files",
            # About 8.2 MB.
            "huge": "extra/os/x86_64/extra.db",
        }
        await self._fetch_file(http, self.mirror.url + urls[kind])


async def get_mirrors(http: ClientSession) -> List[Mirror]:
    async with http.get("https://archlinux.org/mirrors/status/json/") as r:
        data = await r.json()
        return [Mirror(**mirror) for mirror in data["urls"]]


def filter_mirrors(mirrors: List[Mirror]) -> List[Mirror]:
    print(f"Start: {len(mirrors)} mirrors.")
    countries = {"NL", "BE", "DE", "DK", "SE", "NO"}

    now = datetime.now(timezone.utc)
    mirrors = [m for m in mirrors if m.is_ok(countries) and m.is_fresh(now)]
    print(f"Freshness: {len(mirrors)} mirrors.")

    mirrors.sort(key=lambda m: m.duration_stddev)

    return mirrors


async def fetch_many(
    http: ClientSession, mirrors: List[MirrorStats], kind: str, n: int
) -> None:
    """
    Fetch a file `n` times per mirror, and record the stats. We sleep a bit in
    between to not happer the servers too much, and we shuffle the list to even
    out the effects of request order, if there is any.
    """
    sleep_seconds = 0.1
    for _ in range(n):
        random.shuffle(mirrors)
        await asyncio.sleep(sleep_seconds)
        async with asyncio.TaskGroup() as tg:
            for m in mirrors:
                tg.create_task(m.fetch_file(http, kind))

    for m in mirrors:
        m.refresh_stats()


async def main() -> None:
    timeout = aiohttp.ClientTimeout(
        # Timeouts are in seconds.
        sock_connect=3.0,
        sock_read=5.0,
    )
    connector = aiohttp.TCPConnector(
        # Cache DNS lookups forever; we want to measure the speed of the mirror,
        # not of our DNS server.
        use_dns_cache=True,
        ttl_dns_cache=None,
        # Do not limit the total number of open connections on this client.
        # We want to keep connections open to all hosts. Per host though, we
        # only make one concurrent request.
        limit=0,
        limit_per_host=1,
    )

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http:
        mirrors = [MirrorStats(m) for m in filter_mirrors(await get_mirrors(http))]

        # For each mirror, try to fetch the `lastsync` file, and measure how
        # long that took. The initial measurement is not yet that interesting,
        # because it includes the TLS handshake, but for subsequent ones, that's
        # how we get the latencies.
        print("Measuring initial fetch ...")
        await fetch_many(http, mirrors, "small", 3)

        mirrors.sort(key=lambda m: m.rate_bps_upper, reverse=True)
        for m in mirrors:
            print(m)

        # We discard the slowest mirrors, and collect more data from the most
        # promising ones.
        print("Round 2: ")
        mirrors = mirrors[:30]
        await fetch_many(http, mirrors, "small", 2)

        mirrors.sort(key=lambda m: m.rate_bps_upper, reverse=True)
        for m in mirrors:
            print(m)

        queue = [(-m.rate_bps_upper, m) for m in mirrors[:20]]
        heapq.heapify(queue)

        kind_rounds = {
            "medium": 15,
            "large": 10,
            "huge": 5,
        }

        for kind, rounds in kind_rounds.items():
            for round in range(rounds):
                print(f"Round {kind}:{round}")
                candidates = []
                for k in range(5):
                    _prio, m = heapq.heappop(queue)
                    candidates.append(m)

                for m in candidates:
                    print(m)
                    await m.fetch_file(http, kind)
                    m.refresh_stats()
                    heapq.heappush(queue, (-m.rate_bps_upper, m))
                    print(m)

        with open("mirrors.tsv", "w", encoding="utf-8") as f:
            f.write("host\tlen\tdt_secs\n")
            for _, m in queue:
                for dx, dt in zip(m.lens, m.dt_secs):
                    f.write(f"{m.mirror.hostname()}\t{dx}\t{dt:.5f}\n")

        return False

        # For the top candidates, refine the stats with a few more requests.
        print("Measuring more fetch times ...")
        await fetch_lastsync_many(http, mirrors, 5)

        mirrors.sort(key=lambda m: m.mid_lastsync_secs())
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.lastsync_secs,
            )

        # And for the top 15 we add a few more data points, to be sure.
        mirrors = mirrors[:15]
        print("Measuring small file fetch times ...")

        # Now we start fetching the core.db files. This we do sequentially,
        # because now we are measuring throughput, and if we run too much in
        # parallel, we saturate our connection.
        for _ in range(2):
            for m in mirrors:
                await m.fetch_small_file(http)

        mirrors.sort(key=lambda m: max(m.rate_bps), reverse=True)
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.rate_bps,
            )

        # Throw away the slowest 5, and do a few more passes. Only at this point,
        # the congestion control limits start to widen, and the later fetches are
        # generally faster than the initial ones.
        print("Measuring large file fetch times ...")
        mirrors = mirrors[:10]
        for _ in range(3):
            for m in mirrors:
                await m.fetch_large_file(http)

        mirrors.sort(key=lambda m: sum(m.rate_bps), reverse=True)
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.rate_bps,
            )

        print("Measuring large file fetch times, final ...")
        mirrors = mirrors[:5]
        for _ in range(3):
            for m in mirrors:
                await m.fetch_large_file(http)

        mirrors.sort(key=lambda m: sum(m.rate_bps), reverse=True)
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.rate_bps,
            )

        # TODO: Could do a priority queue ordered on the upper bound of a
        # confidence interval for the throughput. Then explore/exploit would
        # test the right hosts in order.

        print()
        for m in mirrors:
            rate_mbps = sum(m.rate_bps) / len(m.rate_bps) / 1e6
            print(f"# {rate_mbps:.1f} MB/s")
            print(f"Server = {m.mirror.url}$repo/os/$arch")


if __name__ == "__main__":
    asyncio.run(main())
