#!/usr/bin/env python3
# Copyright 2024 Ruud van Asseldonk
# See CC0 dedication in the repository root.

"""
Expbackup prints which snapshots to delete to keep exponentiall spaced backups.

Usage:

    expbackup.py <directory>

Args:

    <directory>   A directory that contains entries named "YYYY-MM-DD*"
"""

from datetime import date
from itertools import zip_longest

import os
import sys

verbose = False

dates: list[date] = []
for name in os.listdir(sys.argv[1]):
    parts = name.split("-", maxsplit=4)
    if all(part.isdigit() for part in parts[0:3]):
        dates.append(date(int(parts[0]), int(parts[1]), int(parts[2])))

dates.sort()


intervals = [
    1,  # Daily
    7,  #  Weekly
    7 * 5,  # ~Monthly
    7 * 15,  # 3-4 times per year, ~quarterly.
    7 * 30,  # 1-2 times per year, ~semiannually.
    7 * 60,  # One year and 2 months, ~annually.
]
# Alternatively we can do powers of two, which feels more principled.
intervals = [
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096
]

counters = [0 for _ in intervals]
frontier: list[list[date]] = [[] for _ in intervals]

# We go over the dates from old to new, and every time one of the multiples
# rolls over, we record the date in the frontier for that multiple.
for d in dates:
    t = d.toordinal()
    t_counters = [t // iv for iv in intervals]
    if verbose:
        print(d, t, t_counters)
    for i, (ct, cf) in enumerate(zip(t_counters, counters)):
        if ct > cf:
            counters[i] = ct
            frontier[i].insert(0, d)

if verbose:
    for iv, ds in zip(intervals, frontier):
        print(f"{iv:>4}", " ".join(f"{d}" for d in ds))

# Then we go over the multiples in zig-zag order, and rank all the dates. First
# we keep one date from every multiple, then the second date, etc. This rankes
# dates from most important (low rank number) to least important (high number).
# We go from multiples of a small number (e.g. daily) first to large number
# (e.g. ~yearly), and from most recent rollover to oldest rollover.

rank = 0
ranks: dict[date, int] = {}
for f_dates in zip_longest(*frontier):
    for d in f_dates:
        if (d is not None) and (d not in ranks):
            ranks[d] = rank
            rank += 1

print("DATE        RANK  DROP")
for d in dates:
    r = ranks[d]
    dr = rank - r
    marker = " <=" if r == rank - 1 else ""
    print(f"{d}  {r:>4}  {dr:>4}{marker}")
