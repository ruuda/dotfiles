#!/usr/bin/env python3

"""
Usage: split-cue.py <cuefile> [<audiofile>]

If <audiofile> is not provided, it is assumed to be <cuefile> but with the .cue
extension replaced by .flac.
"""

import os
import subprocess
import sys

from typing import Iterable, Tuple

def run(*cmd: str) -> Iterable[str]:
    """
    Run a command, return its stdout line by line.
    """
    out = subprocess.run(cmd, capture_output=True, check=True, encoding='utf-8', errors='replace')
    return out.stdout.splitlines()


def breakpoints(cue_fname: str) -> Iterable[str]:
    """
    Return the timecodes of track boundaries, including the starting 00:00.
    """
    yield '00:00.00'
    yield from run('cuebreakpoints', '--append-gaps', cue_fname)
    # 'flac --until' interprets -0 as the end of the file.
    yield '-0'


def track_infos(cue_fname: str) -> Iterable[Tuple[str, str]]:
    """
    Return the track number and title of every track in the file.
    """
    for line in run('cueprint', '--track-template', '%n %t\n', cue_fname):
        track_num, title = line.split(' ', maxsplit=1)
        yield track_num, title


def disc_info(cue_fname: str) -> Iterable[str]:
    """
    Return the performer and album title.
    """
    return run('cueprint', '--disc-template', '%P\n%T\n', cue_fname)


def main() -> None:
    if len(sys.argv) == 2:
        cue_fname = sys.argv[1]
        audio_fname = os.path.splitext(cue_fname)[0] + '.flac'

    elif len(sys.argv) == 3:
        cue_fname = sys.argv[1]
        audio_fname = sys.argv[2]

    else:
        print(__doc__)
        sys.exit(1)

    timecodes = list(breakpoints(cue_fname))
    infos = list(track_infos(cue_fname))
    performer, album = disc_info(cue_fname)

    for start, end, (track_num, title) in zip(timecodes, timecodes[1:], infos):
        subprocess.run(
            [
                'flac',
                '-8',
                '--exhaustive-model-search',
                f'--skip={start}',
                f'--until={end}',
                f'--tag=TITLE={title}',
                f'--tag=TRACKNUMBER={track_num}',
                f'--tag=ALBUMARTIST={performer}',
                f'--tag=ALBUM={album}',
                audio_fname,
                f'--output-name={track_num} - {title.replace("/", "-")}.flac',
            ],
            check=True,
        )


if __name__ == '__main__':
    main()
