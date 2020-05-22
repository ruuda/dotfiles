#!/usr/bin/env python3

# btrfs-snapsync.py -- Sync subvolumes between two btrfs filesystems.
# Written in 2020 by Ruud van Asseldonk.
#
# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

"""
Sync read-only subvolumes between two btrfs filesystems in a manner that
preserves as much sharing as possible, without relying on btrfs internals,
to keep the two file systems as isolated as possible, to prevent cascading
corruption in the event of btrfs bugs.

Usage:

    btrfs-snapsync.py <source-dir> <dest-dir>

Source-dir should contain subvolumes named YYYY-MM-DD. Those will be replicated
as read-only subvolumes in the destination directory.

Sync is done with rsync, using a set of flags to optimize for btrfs, in order to
minimize fragmentation and maximize sharing between subvolumes.

It is assumed that subvolumes whose dates are closer together share more, so
when picking a base subvolume for transfer, the existing subvolume with the
nearest date is used as a starting point. This works both forward and backward
in time.
"""

import os
import os.path
import sys
import datetime

from datetime import date
from typing import Optional, Set, Tuple


def list_subvolumes(path: str) -> Set[date]:
    return {
        date.fromisoformat(dirname)
        for dirname
        in os.listdir(path)
    }


def hausdorff_distance(x: date, ys: Set[date]) -> Tuple[int, date]:
    """
    Return the date in ys that is closest to x,
    and the number of days they are apart.
    """
    assert len(ys) > 0, 'Need to have at least one base snapshot to start from.'
    x_day_number = x.toordinal()
    candidates = (
        (abs(x_day_number - y.toordinal()), y)
        for y in ys
    )
    return min(candidates)


def sync_one(src: str, dst: str) -> Optional[date]:
    """
    From the snapshots that are present in src and missing in dst, pick the one
    that is closest to an existing snapshot in dst, and sync it. Returns the
    snapshot synced, or none if src and dst are already in sync.
    """
    src_subvols = list_subvolumes(src)
    dst_subvols = list_subvolumes(dst)
    missing_subvols = src_subvols - dst_subvols

    if len(missing_subvols) == 0:
        return None

    # Find the missing date closest to an existing date, and the existing date
    # that it is closest to.
    transfer_candidates = (
        (*hausdorff_distance(x, dst_subvols), x)
        for x in missing_subvols
    )
    best_candidate = min(transfer_candidates)
    num_days, base_date, sync_date = best_candidate

    print(num_days, base_date, sync_date)
    return sync_date


def main(src: str, dst: str) -> None:
    while True:
        synced_day = sync_one(src, dst)
        if synced_day is None:
            break


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    else:
        main(sys.argv[1], sys.argv[2])
