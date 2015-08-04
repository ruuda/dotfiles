# Keep history for 1000 commands.
HISTFILE=~/.histfile
HISTSIZE=1000
SAVEHIST=1000

# Change dir automatically without the cd command.
setopt autocd

# Use Emacs-style controls (even though I use Vim).
bindkey -e

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

# Customise the prompt, first load colours to do so.
autoload -U colors
colors

# Start with a newline, then user@host in green, then three components of the
# working directory, then a dollar in white. (There is no different charater for
# a root prompt, as root does not use this .zshrc anyway.)
PROMPT="
%{$fg[green]%}%n@%m%{$reset_color%} %3~ %{$fg[white]%}$%{$reset_color%} "
