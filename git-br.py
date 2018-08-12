#!/usr/bin/env python3

# git-br.py -- Git branch with tabular alignment.
# Written in 2018 by Ruud van Asseldonk.
#
# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

# Expects output from "git branch" with the following --format:
#
#     %(HEAD)%00%(objectname:short=7)%00%(refname)%00%(refname:short)%00
#     %(upstream)%00%(upstream:short)%00%(upstream:track)
#
# See also the alias line in my .gitconfig.

import sys
import typing


class Branch(typing.NamedTuple):
    head: str
    hash_short: str
    refname: str
    refname_short: str
    upstream: str
    upstream_short: str
    upstream_track: str


def parse_line(line: str) -> Branch:
    # Split at null separators in the format string, remove trailing newline.
    return Branch(*line[:-1].split('\0'))


def get_children(branches, parent_refname):
    return [
        (branch, get_children(branches, branch.refname))
        for branch in branches
        if branch.upstream == parent_refname
    ]


def flatten(indent, branch, children):
    yield branch._replace(refname_short=indent + branch.refname_short)
    for child, its_children in children:
        yield from flatten(indent + '  ', child, its_children)


def ljust(xs, n):
    return [x.ljust(n) for x in xs]


def rjust(xs, n):
    return [x.rjust(n) for x in xs]


def fmap(f, xs):
    return Branch(*(f(x) for x in xs))


def apply(fs, xs, ys):
    return Branch(*(f(x, y) for f, x, y in zip(fs, xs, ys)))


branches = [parse_line(line) for line in sys.stdin]
refnames = {branch.refname for branch in branches}

# Make all branches roots of which the upstream is not in the list (such as
# when the upstream is a remote branch, but remotes are not listed).
branches = [
    branch._replace(upstream='') if branch.upstream not in refnames else branch
    for branch in branches
]

# Order children below their parents with indented short refname.
branches = [
    indented
    for branch, children in get_children(branches, '')
    for indented in flatten('', branch, children)
]

# Transpose list of branches to columns of values. Align each column.
# Then transpose back.
aligns = Branch(
    head=rjust,
    hash_short=ljust,
    refname=ljust,
    refname_short=ljust,
    upstream=ljust,
    upstream_short=ljust,
    upstream_track=rjust
)
columns = Branch(*zip(*branches))
widths = fmap(lambda col_values: max(len(x) for x in col_values), columns)
aligned = [Branch(*fields) for fields in zip(*apply(aligns, columns, widths))]

reset       = '\033[0m'
reset_color = '\033[39;49m'
bold        = '\033[1m'
yellow      = '\033[33m'
blue        = '\033[34m'
cyan        = '\033[36m'
white       = '\033[37m'

for b in aligned:
    print(f'{bold + "●" if b.head == "*" else " "} '
          f'{yellow}{b.hash_short}{reset_color} '
          f'{b.refname_short} '
          f'{cyan}{b.upstream_track}{reset_color} '
          f'{blue}{b.upstream_short}{reset}')
