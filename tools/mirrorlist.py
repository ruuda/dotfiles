#!/usr/bin/env python3

# mirrorlist.py -- Select the fastest Arch Linux Mirror
# Written in 2025 by Ruud van Asseldonk

# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

from __future__ import annotations

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
        return urlparse(self.url).hostname


class MirrorStats(NamedTuple):
    """
    A mirror, together with mutable statistics about it.
    """

    mirror: Mirror

    # Observations of how long it took to fetch the `lastsync` file, in seconds.
    lastsync_secs: List[float]

    # Errors observed while measuring.
    errors: List[ClientError]

    @staticmethod
    def new(mirror: Mirror) -> MirrorStats:
        return MirrorStats(
            mirror,
            lastsync_secs=[],
            errors=[],
        )

    def min_lastsync_secs(self) -> float:
        """Return the minimum observed lastsync fetch time."""
        return min(self.lastsync_secs)

    def mid_lastsync_secs(self) -> float:
        """Return the median observed lastsync fetch time."""
        return statistics.quantiles(self.lastsync_secs, n=2)[0]

    async def fetch_lastsync_secs(self, http: ClientSession) -> None:
        """
        Fetch the `lastsync` file, and record how long that took in the stats.
        """
        t0 = time.monotonic()
        try:
            async with http.get(self.mirror.url + "lastsync") as r:
                _timestamp = await r.text()
                t1 = time.monotonic()
                self.lastsync_secs.append(t1 - t0)

        except ClientError as exc:
            self.errors.append(exc)


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


async def fetch_lastsync_once(http: ClientSession, mirrors: List[MirrorStats]) -> None:
    """
    For a group of mirrors in parallel, measure how long it takes to "ping"
    them, by fetching the lastsync file, once for every mirror.
    """
    async with asyncio.TaskGroup() as tg:
        for m in mirrors:
            tg.create_task(m.fetch_lastsync_secs(http))


async def fetch_lastsync_many(
    http: ClientSession, mirrors: List[MirrorStats], n: int
) -> None:
    """
    Fetch the lastsync file `n` times per mirror, and record the durations. We
    sleep a bit in between to not hammer the servers too much, and we shuffle
    the list to even out the effects of request order, if there is any.
    """
    sleep_seconds = 0.1
    for _ in range(n):
        random.shuffle(mirrors)
        await asyncio.sleep(sleep_seconds)
        await fetch_lastsync_once(http, mirrors)


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
        mirrors = [MirrorStats.new(m) for m in filter_mirrors(await get_mirrors(http))]

        # For each mirror, try to fetch the `lastsync` file, and measure how
        # long that took. This measurement is not yet that interesting though,
        # because it includes the TLS handshake, so we do this primarily to
        # establish all connections. Then we fetch again, to get a better sense
        # of how long it really takes.
        sleep_secs = 0.1
        print("Measuring initial fetch ...")
        await fetch_lastsync_once(http, mirrors)
        await fetch_lastsync_many(http, mirrors, 2)

        # Keep the top 25 fastests mirrors, based on the fastest samples.
        # At this point we are looking for _potential_, and not interested in
        # outliers.
        mirrors.sort(key=lambda m: m.min_lastsync_secs())
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.lastsync_secs,
            )

        mirrors = mirrors[:25]

        # For the top candidates, refine the stats with a few more requests.
        print("Measuring more fetch times ...")
        await fetch_lastsync_many(http, mirrors, 4)

        mirrors.sort(key=lambda m: m.mid_lastsync_secs())
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.lastsync_secs,
            )

        # And for the top 15 we add a few more data points, to be sure.
        mirrors = mirrors[:15]
        print("Measuring more fetch times ...")
        await fetch_lastsync_many(http, mirrors, 4)

        mirrors.sort(key=lambda m: m.mid_lastsync_secs())
        for m in mirrors:
            mm = m.mirror
            print(
                f"{mm.country_code} delay={mm.delay} dt={mm.duration_avg:.3f} sd={mm.duration_stddev:.3f} {mm.hostname()}",
                m.lastsync_secs,
            )


if __name__ == "__main__":
    asyncio.run(main())
