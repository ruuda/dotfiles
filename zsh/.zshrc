# Keep history for 1000 commands.
HISTFILE=~/.histfile
HISTSIZE=1000
SAVEHIST=1000

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

# Enable completion.
autoload -Uz compinit
compinit

# Set preferred tools.
export CC=clang
export CXX=clang++
export EDITOR=vim

# Colour ls output by default.
alias ls='ls --color=auto'

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
