#!/usr/bin/zsh

convert "$1" \
  -font Impact \
  -pointsize "$2" -strokewidth "$(($2 * 0.04))" \
  -fill white -stroke black \
  -gravity north -annotate +0+0 "$3" \
  -gravity south -annotate +0+0 "$4" \
  "$5"
