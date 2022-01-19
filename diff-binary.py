#!/usr/bin/env python3

# diff-binary.py -- Diff binary files with insertions and deletions.
# Written in 2022 by Ruud van Asseldonk.
#
# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

"""
Usage: diff-binary.py <a> <b>

TODO: Make the hex decoding optional.
"""

import sys
import difflib

def load(fname: str) -> bytes:
    with open(fname, 'r', encoding='utf-8') as f:
        # Cut off the "0x"
        return bytes.fromhex(f.read()[2:])


def print_hex(b: bytes, prefix: str = '  ', suffix: str = '\n'):
    chunk_size = 16
    for k in range(0, len(b), chunk_size):
        print(prefix, end='')
        span = b[k:k + chunk_size]

        # Pass 1: Hex
        for i in range(0, chunk_size):
            hex_char = f'{span[i]:02x} ' if i < len(span) else '   '
            print(hex_char, end='')

        # Pass 2: Unicode
        for i in range(0, chunk_size):
            char = chr(span[i]) if i < len(span) else ' '
            char = char if char.isprintable() else '.'
            print(char, end='')

        print(end=suffix)


a = load(sys.argv[1])
b = load(sys.argv[2])

red = '\x1b[31m'
green = '\x1b[32m'
reset = '\x1b[0m\n'

matcher = difflib.SequenceMatcher(None, a, b)
for tag, i1, i2, j1, j2 in matcher.get_opcodes():
    if tag == 'equal':
        print_hex(a[i1:i2], prefix='  ')
    elif tag == 'delete':
        print_hex(a[i1:i2], prefix=f'{red}- ', suffix=reset)
    elif tag == 'insert':
        print_hex(b[j1:j2], prefix=f'{green}+ ', suffix=reset)
    elif tag == 'replace':
        print_hex(a[i1:i2], prefix=f'{red}- ', suffix=reset)
        print_hex(b[j1:j2], prefix=f'{green}+ ', suffix=reset)
    else:
        raise Exception('Invalid opcode.')
