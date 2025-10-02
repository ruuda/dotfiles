#!/usr/bin/env python3

"""
brightness.py -- Quickly set the brightness of all displays.

SYNOPSIS

  brightness.py <brightness>

ARGUMENTS

  <brightness>   Brightness value between 0 and 100 inclusive.

RATIONALE

  Setting brightness with 'ddcutil --display X setvcp' is slow. That's because
  it has to figure out which i2c devices belong to a display, which it does
  by probing. If we set brightness for multiple displays, we even wait twice!
  We can do that a lot faster by just checking which /sys/class/drm/card is
  connected, and which i2c devices belong to those.
"""

import sys
import os
import subprocess

if len(sys.argv) != 2:
    print(__doc__.strip())
    sys.exit(1)

# TODO: Do I need to modprobe i2c-dev? My old Bash version needed to?

aux_names = []
bus_numbers = []

# In /sys/class/drm/cardX-DP-Y we can find the connected external displays.
# The card dir *sometimes* contains an i2c directory directly, but I also have
# displays where this is not the case. All of them contain a drm_dp_aux dir
# though, which contain a name that we can match to /sys/class/i2c-dev. So as a
# first step, extract those names for each of the connected displays.
for card in os.listdir("/sys/class/drm"):
    if not card.startswith("card") or "-DP-" not in card:
        continue

    card_dir = f"/sys/class/drm/{card}"

    status = open(f"{card_dir}/status", "r", encoding="ascii").read().strip()
    if status != "connected":
        continue

    for dir in os.listdir(card_dir):
        if dir.startswith("drm_dp_aux"):
            aux_fname = f"{card_dir}/{dir}/name"
            aux_name = open(aux_fname, "r", encoding="ascii").read().strip()
            aux_names.append(aux_name)

# Loop over the i2c devices to find the ones matching the displays we found.
for i2c in os.listdir("/sys/class/i2c-dev"):
    i2c_dir = f"/sys/class/i2c-dev/{i2c}"
    name = open(f"{i2c_dir}/name", "r", encoding="ascii").read().strip()
    if name in aux_names:
        bus_numbers.append(i2c.removeprefix("i2c-"))

# Finally, we can use ddcutil to set the brightness. Property 10 is the
# brightness.
procs = [
    subprocess.Popen(["ddcutil", "setvcp", f"--bus={bus}", "10", sys.argv[1]])
    for bus in bus_numbers
]
for proc in procs:
    proc.wait()
