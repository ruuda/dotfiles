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

def get_native_packages():
    return get_from_pacman('-Qnq')

def get_explicit_native_packages():
    return get_from_pacman('-Qneq')

def get_explicit_native_root_packages():
    return get_from_pacman('-Qnettq')

def print_list(packages, message):
    if len(packages) > 0:
        print(message)
        for pkg in sorted(packages):
            print('  ' + pkg)

def main():
    explicit_native_desired = get_from_file('packages')
    explicit_native_root = get_explicit_native_root_packages()
    explicit_native = get_explicit_native_packages()
    all_native = get_native_packages()

    # Find packages which are not installed explicitly, but which should be
    # according to the list, and vice versa.
    missing_explicit_pkgs = set(explicit_native_desired).difference(explicit_native)
    unexpected_pkgs = set(explicit_native).difference(explicit_native_desired)

    # Missing explicit packages can be installed but not explicitly, or not
    # installed at all.
    missing_pkgs = missing_explicit_pkgs.difference(all_native)
    non_explicit_pkgs = missing_explicit_pkgs.difference(missing_pkgs)

    # Unexpected packages can either be explicit while they should be a
    # dependency, or they can be totally new.
    unexpected_deps = unexpected_pkgs.difference(explicit_native_root)
    unexpected_new = unexpected_pkgs.difference(unexpected_deps)

    print_list(missing_pkgs,
        '\nThe following desired native packages are not installed:\n')

    print_list(non_explicit_pkgs,
        '\nThe following native packages should be reinstalled with --asexplicit:\n')

    print_list(unexpected_deps,
        '\nThe following native packages should be reinstalled with --asdeps:\n')

    print_list(unexpected_new,
        '\nThe following native packages might be uninstalled or added to the list:\n')

main()
