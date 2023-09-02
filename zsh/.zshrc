# Keep history for 50000 commands.
HISTFILE=~/.histfile
HISTSIZE=50000
SAVEHIST=50000

# Do not put duplicate entries in the history. What is the point of pressing the
# up arrow thirty times and nothing happens?
setopt hist_ignore_dups

# Do not record a command in the history if it is prefixed by a space.
setopt hist_ignore_space

# Write history immediately instead of at exit. This ensures that history is not
# lost even when the shell is not properly terminated.
setopt inc_append_history

# Change dir automatically without the cd command.
setopt autocd

# Use Emacs-style controls (even though I use Vim).
bindkey -e

# Make all keys work in GNOME terminal. To generate the ~/.zkbd/$TERM file, run
# `autoload zkbd` and `zkbd`.
source ~/.zkbd/$TERM
[[ -n ${key[Home]}   ]] && bindkey "${key[Home]}"   beginning-of-line
[[ -n ${key[End]}    ]] && bindkey "${key[End]}"    end-of-line
[[ -n ${key[Delete]} ]] && bindkey "${key[Delete]}" delete-char

# Use FZF for history search (Ctrl + R), and use Ctrl + T to insert a file name
# from the current directory.
source /usr/share/fzf/key-bindings.zsh
# For some reason FZF started not respecting the default chronological order in
# reverse-i-search, make it do that after all. Also make the color integrate a
# bit more nicely. Edit: remove the --no-sort again, I think it was working
# better without it after all ... not sure what changed there.
export FZF_DEFAULT_OPTS="--color=dark,bg+:0"

# Make Ctrl + Z discard the current input, and bring it up again after the next
# command has finished. Ctrl-Z on empty input will still background the process.
ctrl-z-stash() {
  emulate -LR zsh
  if [[ $#BUFFER -eq 0 ]]; then
    bg
    zle redisplay
  else
    zle push-input
  fi
}
zle -N ctrl-z-stash
bindkey "^Z" ctrl-z-stash

# Use Vim-inspired navigation key bindings in Emacs mode. This helps navigating
# those really long commands when you need to fix the typo right in the middle.
bindkey "^E" vi-forward-blank-word-end
bindkey "^W" vi-forward-blank-word
bindkey "^B" backward-word

# Enable completion.
autoload -Uz compinit
compinit

# Set preferred tools.
export CC='clang'
export CPP='clang -E'
export CXX='clang++'
export EDITOR='vim'

# Add ~/.local/bin to the path.
export PATH="$PATH:$HOME/.local/bin:$HOME/.nix-profile/bin"

# Allow cd'ing into subdirectories of ~/repos and ~/profile from anywhere.
export CDPATH=".:$HOME/repos:$HOME/profile"

# I only use Nix with locally pinned files, there should not be any global Nix
# search path. Unset the one that came with the AUR "nix" package.
unset NIX_PATH

# Add a pinned version of Nix 2.3 to the path.
# Nix 2.4 broke the entire CLI and there is no easy way to avoid it,
# so stick with 2.3 for most things.
alias nix23='/nix/store/9hkh1fx8z1frgbz2nawr0mnyvizrb8yk-nix-2.3.15/bin/nix'

nix_flags='--extra-experimental-features nix-command --extra-experimental-features flakes'

# But I do want to use flakes some times too, so add a Nix with flakes as well.
alias nix210="/nix/store/l0iqmrkw6l78fsixm8l9j6w52372wkhm-nix-2.10.3/bin/nix ${nix_flags}"
alias nix214="/nix/store/9yyfg6fzhs4sf454q2rf179kp3miy9mg-nix-2.14.1/bin/nix ${nix_flags}"
alias nix215="/nix/store/q6r9kwmidiy6wx1w1nf3ff0q40sfq4dg-nix-2.15.1/bin/nix ${nix_flags}"
alias nix216="/nix/store/a3g640wlfhxaqdw0nla62vn0m3fc4q6p-nix-2.16.1/bin/nix ${nix_flags}"
alias nix217="/nix/store/3wqasl97rjiza3vd7fxjnvli2w9l30mk-nix-2.17.0/bin/nix ${nix_flags}"

# And default to a recent Nix from now on.
alias nix='nix217'

# Colour ls and grep output by default. Also prevent ls from quoting names with
# spaces. Furthermore, list directories before files.
alias ls='ls --color=auto --quoting-style=literal --group-directories-first'
alias grep='grep --color=auto'
alias egrep='egrep --color=auto'

# MPV with loudness normalization, for watching movies or series without having
# to turn up the volume if there’s a conversation and then having to turn it
# down when there’s an explosion. We add a compressor with 40ms attack and 3s
# release (quite long, otherwise the effect is very apparent and that destroys
# the content).
alias mpv-loudnorm='gnome-session-inhibit mpv --audio-channels=stereo --af="acompressor=ratio=6:attack=40:release=3000,loudnorm=I=-18"'

# Journalctl is quite verbose by default, and its timestamp does not include the
# year. Fix that by picking ISO 8601 timestamps and omitting the hostname.
# (I wish there were a mode that replaces the T in ISO 8601 with a normal space.
# It hurts readability and there is no ambiguity anyway. </rant>)
alias journalctl='journalctl --output=short-iso --no-hostname'

# Use Git's diff functionality instead of GNU Diff. Git's is far superior. Use a
# function instead of an alias so we can define a custom autocomplete that
# completes files, not Git stuff.
function diff() {
  git diff --no-index "$@"
}

# Autocomplete the diff alias.
compdef '_path_files _path_files' diff

# Allow exit the Vim way.
alias :q='exit'

# Aliases to cd up multiple directories.
alias ...='cd ../..'
alias ....='cd ../../..'
alias .....='cd ../../../..'

# Enter a Nix development environment, and create an indirect GC root for it
# at .nix-devenv, to ensure that it does not get garbage collected during the
# next 'nix-store --gc'.
function nsh {
  nix23 build --no-link
  nix-store --add-root .nix-devenv --indirect --realize $(nix23 path-info) > /dev/null
  nix23 run -c $SHELL
}

# Same but then for using flakes.
function fsh {
  devenv_id="$(pwd | b2sum --length 64 | awk '{ print $1 }')-$(basename $PWD)"
  gcroot="${HOME}/.cache/nix/gcroots/${devenv_id}"

  # Build the devShell itself, record its store path.
  shell_storepath=$(nix216 build --keep-env-derivations --no-link --print-out-paths .#devShells.x86_64-linux.default)

  # Adding a GC root for just the shell is insufficient, because Nix needs the
  # flake inputs to determine the store path of the shell. `flake archive` can
  # give us the store paths for the flake inputs, then we pass all of those to
  # nix-store --add-root along the the shell itself.
  nix216 --offline flake archive --dry-run --json \
    | jq --raw-output '.inputs | .. | .path? | select(. != null)' \
    | xargs --max-procs=1 \
    nix-store --add-root ${gcroot} --indirect --realise ${shell_storepath} \
    > /dev/null

  # Finally, enter the development shell itself.
  nix216 --offline develop --command $SHELL
}

# The Gnome keyring does not support ed25519 keys, and it is annoying to have to
# unlock the key every time. Therefore start an ssh-agent that is shared among
# all shells, but do not load a key immediately. A manual ssh-add is still
# required, but after that the key will remain loaded and accessible to new
# shells.

# Store information about the running SSH agent in ~/.ssh/environment.
SSH_ENV=$HOME/.ssh/environment

# To start an ssh agent, run the program, which prints shell script that sets
# the right environment variables. It also echoes the PID, suppress that by
# commenting it with sed. Then make the file executable and evaluate it.
function start_ssh_agent {
  ssh-agent | sed 's/^echo/#echo/' > "${SSH_ENV}"
  chmod 600 "${SSH_ENV}"
  . "${SSH_ENV}" > /dev/null
}

# If an environment file exists, run it to pick up the correct environment
# variables. If it turns out that the agent is no longer running, start a new
# agent. This will update the environment file. If there was no environment
# file, also start a new agent (and write the environment file).
if [ -f "${SSH_ENV}" ]; then
  . "${SSH_ENV}" > /dev/null
  ps ${SSH_AGENT_PID} | grep ssh-agent$ > /dev/null || {
    start_ssh_agent;
  }
else
  start_ssh_agent;
fi

# Set suffix aliases to open certain files with an editor by default.
alias -s cpp=gvim
alias -s h=gvim
alias -s md=gvim
alias -s rs=gvim

# Make R store local packages in a sane location.
export R_LIBS_USER="$HOME/.local/lib/R/library"

# Customise the prompt, first load the plugins to set the colour and get the Git
# status.
autoload -Uz colors
autoload -Uz vcs_info
colors

# If any Nix store paths are on the path, extract the package name part from the
# directory. These act as a kind of virtualenv indicator. We first locate all
# Nix store paths that occur in the path, printing the matches, one per line.
# Then with Awk we cut off the store path prefix, and print everything on a
# single line, by setting the output record separator (ORS) to the empty string.
# Truncate to 30 characters if there's a lot of store paths on the path.
nix_paths=$(
  echo $PATH                                                  \
  | grep -E '/nix/store/[a-z0-9]{32}-([^/]+)' --only-matching \
  | awk 'ORS = ""; { print substr($1, 45, length($1)) " " }'  \
  | awk '{ if (length($0) > 30) { print substr($0, 0, 30) "… " } else { print $0 }}'
)
# Alternatively, for my newer workflow, we can tell the name from the GC root.
if [[ -v NIX_GCROOT ]]; then
  nix_paths=$(echo $NIX_GCROOT | awk '{ print substr($0, 45) " " }')
fi
nix_info_msg="%{$fg[blue]%}${nix_paths}%{$reset_color%}"

# Retrieve source control status before printing the prompt.
precmd() { vcs_info }

# Enable info for Git and Subversion. Do detect changes in the working
# directory. Format source control info as the branch in red, optionally with an
# action in yellow. Staged and unstaged changes will show as a red star and
# green plus.
zstyle ':vcs_info:*' enable git svn
zstyle ':vcs_info:*' check-for-changes true
zstyle ':vcs_info:*' formats "%{$fg[red]%}%b%u%c%{$reset_color%} "
zstyle ':vcs_info:*' actionformats "%{$fg[red]%}%b%u%c %{$fg[yellow]%}%a%{$reset_color%} "
zstyle ':vcs_info:*' unstagedstr "%{$fg[red]%}*"
zstyle ':vcs_info:*' stagedstr "%{$fg[green]%}+"

# Normally, the PS1 variable is evaluated only once, but because the vcs info
# changes, we need to do it on every prompt.
setopt prompt_subst

# Start with a newline, then user@host in green, then three components of the
# working directory, then source control (vcs) info, then a dollar in white.
# (There is no different charater for a root prompt, as root does not use this
# .zshrc anyway.)
PS1='
%{$fg[green]%}%n@%m%{$reset_color%} %3~ ${nix_info_msg}${vcs_info_msg_0_}%{$fg[white]%}$%{$reset_color%} '
