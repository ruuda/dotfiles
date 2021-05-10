#!/usr/bin/bash

# Set monitor brightness. Takes a value between 0 and 100.

if [ $UID != 0 ]; then
  echo "Requires root privileges."
  exit 1
fi

# ddcutil requires this module.
modprobe i2c-dev

# Property 10 is brightness.
ddcutil setvcp --display 1 10 $1
ddcutil setvcp --display 2 10 $1
