#!/bin/env python3

# pkg.py -- Declarative package management utility for Pacman.
# Written in 2016 by Ruud van Asseldonk.
#
# To the extent possible under law, the author has dedicated all copyright and
# related neighbouring rights to this software to the public domain worldwide.
# See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

import subprocess

def get_from_pacman(args):
    cmd = ['pacman', args]
    pacman = subprocess.run(cmd, stdout = subprocess.PIPE)
    output = pacman.stdout.split(b'\n')
    return [pkg.decode('utf-8') for pkg in output if len(pkg) > 0]

def get_from_file(fname):
    with open(fname) as f:
        return [pkg.strip() for pkg in f if len(pkg) > 0]

def get_explicit_native_packages():
    return get_from_pacman('-Qneq')

def get_explicit_native_root_packages():
    return get_from_pacman('-Qnettq')

def main():
    explicit_native_desired = get_from_file('packages')
    explicit_native_root = get_explicit_native_root_packages()
    explicit_native = get_explicit_native_packages()

    # Find packages which are not installed explicitly, but which should be
    # according to the list, and vice versa.
    missing_pkgs = set(explicit_native_desired).difference(explicit_native)
    unexpected_pkgs = set(explicit_native).difference(explicit_native_desired)

    # Unexpected packages can either be explicit while they should be a
    # dependency, or they can be totally new.
    unexpected_deps = unexpected_pkgs.difference(explicit_native_root)
    unexpected_new = unexpected_pkgs.difference(unexpected_deps)

    if len(missing_pkgs) > 0:
        print('The following desired native packages are not installed explicitly:\n')
        for pkg in sorted(missing_pkgs):
            print(pkg)

    if len(unexpected_deps) > 0:
        print('\nThe following native packages should be reinstalled with --asdeps:\n')
        for pkg in sorted(unexpected_deps):
            print(pkg)

    if len(unexpected_new) > 0:
        print('\nThe following native packages might be uninstalled or added to the list:\n')
        for pkg in sorted(unexpected_new):
            print(pkg)

main()
