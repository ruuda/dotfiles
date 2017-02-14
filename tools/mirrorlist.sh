#!/bin/bash

# Script to update the Pacman mirror list with the latest online version, after
# it has changed.

set -e

base='https://www.archlinux.org/mirrorlist/'
args='?country=DE&protocol=https&ip_version=4&ip_version=6&use_mirror_status=on'
curl --cert-status "${base}${args}" | sudo tee /etc/pacman.d/mirrorlist.new > /dev/null
sudo -e /etc/pacman.d/mirrorlist.new
sudo mv /etc/pacman.d/mirrorlist.new /etc/pacman.d/mirrorlist
sudo rm -f /etc/pacman.d/mirrorlist.pacnew
