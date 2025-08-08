#!/usr/bin/env python3

# mirrorlist.py -- Select the fastest Arch Linux Mirror
# Written in 2025 by Ruud van Asseldonk

# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

import json

from typing import Literal, List, NamedTuple
from http.client import HTTPSConnection


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

    # Last
    last_sync: str

    # Supported transport protocol.
    protocol: Literal["https"] | Literal["http"] | Literal["rsync"]

    # Score according to the Arch mirror checker's formula.
    score: float

    # Base repo URL, and details URL.
    url: str
    details: str


def get_mirrors() -> List[Mirror]:
    timeout_seconds = 3.0
    host = "archlinux.org"
    conn = HTTPSConnection(host, timeout=timeout_seconds)
    conn.request("GET", "/mirrors/status/json/", headers={"Host": host})
    response = conn.getresponse()
    assert response.status == 200
    data = json.load(response)
    mirrors: List[Mirror] = data["urls"]
    return mirrors


def main() -> None:
    mirrors = get_mirrors()
    for m in mirrors:
        print(m)


if __name__ == "__main__":
    main()
