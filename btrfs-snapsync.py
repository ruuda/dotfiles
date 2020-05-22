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

    btrfs-snapsync.py [--dry-run] [--single] <source-dir> <dest-dir>

Options:

    --dry-run    Print commands that would be executed but do not execute them.
    --single     Stop after syncing one subvolume, even if more are missing.

Source-dir should contain subvolumes named YYYY-MM-DD. Those will be replicated
as read-only subvolumes in the destination directory.

Sync is done with rsync, using a set of flags to optimize for btrfs, in order to
minimize fragmentation and maximize sharing between subvolumes.

It is assumed that subvolumes whose dates are closer together share more, so
when picking a base subvolume for transfer, the existing subvolume with the
nearest date is used as a starting point. This works both forward and backward
in time.

This command might need to run as superuser.
"""

import os
import os.path
import sys
import datetime
import subprocess

from datetime import date
from typing import Optional, List, Set, Tuple


def run(args: List[str], *, dry_run: bool) -> None:
    if dry_run:
        print('Would run', ' '.join(args))
    else:
        subprocess.run(args, check=True)


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


def sync_one(src: str, dst: str, *, dry_run: bool) -> Optional[date]:
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
    base_dir = base_date.isoformat()
    sync_dir = sync_date.isoformat()

    print(f'Syncing {sync_dir}, using {base_dir} as base.')

    # Create a writeable snapshot of the base subvolume.
    cmd = [
        'btrfs', 'subvolume', 'snapshot',
        os.path.join(dst, base_dir),
        os.path.join(dst, sync_dir),
    ]
    run(cmd, dry_run=dry_run)

    # Sync into it.
    cmd = [
        'rsync',
        '-a',
        '--delete-delay',
        '--inplace',
        '--preallocate',
        '--no-whole-file',
        '--info=progress2',
        os.path.join(src, sync_dir) + '/',
        os.path.join(dst, sync_dir),
    ]
    run(cmd, dry_run=dry_run)

    # Once that is done, make the snapshot readonly.
    cmd = [
        'btrfs', 'property', 'set',
        '-t', 'subvol',
        os.path.join(dst, sync_dir),
        'ro', 'true',
    ]
    run(cmd, dry_run=dry_run)

    return sync_date


def main(src: str, dst: str, *, dry_run: bool, single: bool) -> None:
    while True:
        synced_day = sync_one(src, dst, dry_run=dry_run)

        if synced_day is None:
            break

        if single:
            print('Stopping after one transfer because of --single.')
            break

        if dry_run:
            print('Stopping now to avoid endless loop because of --dry-run.')
            break


if __name__ == '__main__':
    args = list(sys.argv)

    dry_run = '--dry-run' in args
    if dry_run:
        args.remove('--dry-run')

    single = '--single' in args
    if single:
        args.remove('--single')

    if len(args) != 3:
        print(__doc__)
        sys.exit(1)

    else:
        main(args[1], args[2], dry_run=dry_run, single=single)
