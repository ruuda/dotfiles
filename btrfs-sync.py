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
import subprocess
import sys

from subprocess import Popen
from typing import Set


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
    if len(new_snaps) == 0:
        return False

    # If the snapshots are named with ISO-8601 dates as a prefix, then this
    # ensures that we sync from least recent snapshot to most recent one.
    # For fragmentation reasons it may make sense to go the other way around,
    # but this triggers btrfs bugs, if we have snapshots at T1, T2, T3, at the
    # source, and T1 at the destination, and we copy T3, and then we want to
    # copy T2 using {T1, T2} as the clone sources, then the receive fails.
    # (At least, this is my hypothesis, I haven't contructed a minimal repro.)
    target = min(new_snaps)
    print(f":: Next target: {target}")

    cmd_send = ["btrfs", "send", "--proto=0"]

    clone_sources = src_snaps & dst_snaps
    for clone_source in clone_sources:
        cmd_send.append("-c")
        cmd_send.append(clone_source)

    cmd_send.append(target)
    cmd_recv = ["btrfs", "receive", dst_path]

    print(f":: Send: {' '.join(cmd_send)}")
    print(f":: Recv: {' '.join(cmd_recv)}")

    p1 = Popen(cmd_send, cwd=src_path, stdout=subprocess.PIPE)
    p2 = Popen(["pv"], stdin=p1.stdout, stdout=subprocess.PIPE)
    p3 = Popen(cmd_recv, cwd=dst_path, stdin=p2.stdout)
    assert p1.stdout is not None
    assert p2.stdout is not None
    p1.stdout.close()
    p2.stdout.close()

    p1.wait()
    p2.wait()
    p3.wait()
    assert p1.returncode == 0
    assert p2.returncode == 0
    assert p3.returncode == 0

    return True


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
