#!/usr/bin/env python3

# mirrorlist.py -- Select the fastest Arch Linux Mirror
# Written in 2025 by Ruud van Asseldonk

# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

import json
import subprocess

from typing import Iterable, Literal, List, NamedTuple, Set
from http.client import HTTPSConnection
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


class Mirror(NamedTuple):
    """
    The fields here map directly to those documented at
    <https://archlinux.org/mirrors/status/>.
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


def get_mirrors() -> List[Mirror]:
    timeout_seconds = 3.0
    host = "archlinux.org"
    conn = HTTPSConnection(host, timeout=timeout_seconds)
    conn.request("GET", "/mirrors/status/json/", headers={"Host": host})
    response = conn.getresponse()
    assert response.status == 200
    data = json.load(response)
    return [Mirror(**mirror) for mirror in data["urls"]]


def filter_mirrors(mirrors: List[Mirror]) -> List[Mirror]:
    print(f"Start: {len(mirrors)} mirrors.")
    countries = {"NL", "BE", "DE", "DK", "SE", "NO"}

    now = datetime.now(timezone.utc)
    mirrors = [m for m in mirrors if m.is_ok(countries) and m.is_fresh(now)]
    print(f"Freshness: {len(mirrors)} mirrors.")

    mirrors.sort(key=lambda m: m.duration_stddev)

    return mirrors


def ping_hosts_ms(
    hostnames: List[str],
    *,
    n_pings: int,
    period_ms: int,
    interval_ms: int,
) -> Iterable[List[float]]:
    """
    Send `n_pings` pings to each of the hosts, and return the timings in
    milliseconds. This requires `fping` to be installed.
    - `period_ms`: The minimum time between pinging the same host, in ms.
    - `interval_ms`: The minimum time between pinging any two hosts, in ms.
    With fping's default interval of 10ms, when pinging many hosts, we observe
    a high amount of packet loss, maybe the ISP is doing some limiting.
    """
    # fmt:off
    cmd = [
        "fping",
        # "--quiet",
        # Print statistics every 2s. (Yes, this argument is in seconds, while
        # the others are in milliseconds.)
        "--vcount", str(n_pings),
        "--interval", str(interval_ms),
        "--period", str(period_ms),
        *hostnames
    ]
    # fmt:on
    # fping prints ongoing stats to stdout, unless we --quiet it, and then the
    # parseable summary to stderr.
    proc = subprocess.run(cmd, encoding="utf-8", stderr=subprocess.PIPE)
    for line in proc.stderr.splitlines():
        if " : " in line:
            _hostname, more = line.split(" : ", maxsplit=1)
            times_ms = more.split(" ")
            yield [float(dt) for dt in times_ms if dt != "-"]


def main() -> None:
    mirrors = filter_mirrors(get_mirrors())

    print(f"Found {len(mirrors)} mirrors, pinging.")

    hostnames = [m.hostname() for m in mirrors]
    pings_ms = list(ping_hosts_ms(hostnames, n_pings=2, interval_ms=300, period_ms=100))

    for h, p, m in zip(hostnames, pings_ms, mirrors):
        print(
            f"{m.country_code} delay={m.delay} dt={m.duration_avg:.3f} sd={m.duration_stddev:.3f}",
            h,
            p,
        )


if __name__ == "__main__":
    main()
