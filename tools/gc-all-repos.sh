#!/bin/sh

# Usage: ./gc-all-repos.sh [--aggressive] [--auto] PATH
#
# Runs 'git gc' in all directories in PATH which contain a (bare) Git
# repository.

if [ "$1" == "--aggressive" ] || [ "$1" == "--auto" ]; then
  git_args=$1
  basedir=$2
else
  git_args=""
  basedir=$1
fi

echo ":: Enumerating Git repositories in $basedir."

for dir in $(find $basedir -maxdepth 1 -type d); do
  # Check if the directory is a Git repository by running 'rev-parse --git-dir'.
  if git -C $dir rev-parse --git-dir > /dev/null 2> /dev/null; then
    echo ":: Entering $dir ..."
    git -C $dir gc $git_args
    echo ""
  fi
done
