# Keep history for 10000 commands.
HISTFILE=~/.histfile
HISTSIZE=10000
SAVEHIST=10000

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

# Colour ls and grep output by default.
# Also prevent ls from quoting names with spaces.
alias ls='ls --color=auto --quoting-style=literal'
alias grep='grep --color=auto'
alias egrep='egrep --color=auto'

# Allow exit the Vim way.
alias :q='exit'

# Aliases to cd up multiple directories.
alias ...='cd ../..'
alias ....='cd ../../..'
alias .....='cd ../../../..'

# The Gnome keyring does not support ed25519 keys,
# and it is annoying to have to unlock the key every time.
# Add an alias to start ssh-agent and load the key.
alias loadkey='eval $(ssh-agent) && ssh-add'

# Set suffix aliases to open certain files with an editor by default.
alias -s cpp=gvim
alias -s h=gvim
alias -s md=gvim
alias -s rs=gvim

# Customise the prompt, first load the plugins to set the colour and get the Git
# status.
autoload -Uz colors
autoload -Uz vcs_info
colors

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
%{$fg[green]%}%n@%m%{$reset_color%} %3~ ${vcs_info_msg_0_}%{$fg[white]%}$%{$reset_color%} '
