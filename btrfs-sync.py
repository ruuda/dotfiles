#!/usr/bin/env python3

# btrfs-sync.py -- Run btrfs send/receive to sync two snapshot directories.
# Written in 2024 by Ruud van Asseldonk.
#
# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

"""
Usage:

    btrfs-sync.py <src-path> <dst-path>

Both path should be directories that contain snapshots.
"""

import os
import os.path
import sys

from typing import List, Set


def list_snapshots(path: str) -> Set[str]:
    """
    Return all snapshot directories in the directory. Returns the relative path.
    """
    return {
        dirname
        for dirname in os.listdir(path)
        if os.path.isdir(os.path.join(path, dirname))
    }


def sync_one(src_path: str, dst_path: str) -> bool:
    """
    Sync one snapshot that is present in src and not in dst. Returns true when
    such a snapshot did exist, false when the destination is already in sync.
    """
    src_snaps = list_snapshots(src_path)
    dst_snaps = list_snapshots(dst_path)
    new_snaps = src_snaps - dst_snaps

    print(f":: There are {len(new_snaps)} snapshots left to sync.")

    # If the snapshots are named with ISO-8601 dates as a prefix, then this
    # ensures that we sync from most recent snapshot to least recent one.
    target = max(new_snaps)
    print(f":: Next target: {target}")
    return False


def main(src_path: str, dst_path: str) -> None:
    while True:
        did_sync = sync_one(src_path, dst_path)
        if not did_sync:
            break


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
