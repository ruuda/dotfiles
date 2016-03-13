" Enable Pathogen.
execute pathogen#infect()

" Generic
" =======

" Use UTF-8 as encoding.
set encoding=utf-8
set fileencoding=utf-8

" Indent by two spaces please.
set tabstop=2
set shiftwidth=2
set expandtab
set smarttab

" Enable auto-indent and smart indent.
set ai
set si

" Highlight the column after the text width.
set colorcolumn=+1

" Highlight search results, do incremental search.
" set hlsearch -- or not, looks ugly
set incsearch

" Highlight matching brackets for 0.2 seconds.
set showmatch
set mat=2

" Enable filetype detection, and load filetype-specific plugins and
" indentation.
filetype plugin indent on

" Enable visual autocomplete of commands.
set wildmenu

" Enable the ruler.
set ru

" Automatically reload files if they changed outside of Vim, do not ask.
set autoread

" Use Solarized Dark. (But not in a Windows terminal that does not support 256
" colours.)
if &term != 'win32'
  set background=dark
  colorscheme solarized
endif

" Enable syntax highlighting.
syntax enable

" For CtrlP, suggest files from a Git repository. First list all tracked files
" (ls-files), then list all untracked files that are not ignored (second
" invocation of ls-files). Git can list them in one command, but listing
" untracked files is noticeably slower and introduces a delay. By listing these
" files last, CtrlP can start scanning through the tracked files immediately,
" which are also accessed most often.
let g:ctrlp_user_command =
  \ ['.git', 'cd %s && git ls-files && git ls-files --other --exclude-standard']

" With caching enabled, new untracked files will not show up, so disable it.
let g:ctrlp_use_caching = 0

" Open CtrlP with Leader + F in addition to Ctrl + P. It is much more ergonomic.
noremap <Leader>f :CtrlP<Return>

" Filetype specific
" =================

" I cannot get ~/vimfiles/ftplugin working, so this is the second option:
" Rust uses four-space indentation.
au FileType rust set tabstop=4 shiftwidth=4

" Rust builds with Cargo
au FileType rust set makeprg=cargo\ build

" I prefer 80-column files over the default 100.
au FileType rust set textwidth=80

" Disable smart indent and cindent (brackets indent) for TeX files. Setting
" indentexpr to empty ensures that Vim does not mess up things after typing a
" curly bracket. Build TeX with latexmk.
au FileType tex set nosmartindent nocindent indentexpr=
if has("win32") " The dash should not be escaped on Windows.
  au FileType tex set makeprg=latexmk\  -xelatex\ %
else
  au FileType tex set makeprg=latexmk\ \-xelatex\ %
endif

" Disable folding of markdown files.
let g:vim_markdown_folding_disabled=1

" Graphical options
" =================

if has("gui_running")
  " Use Consolas at size 12.
  if has("gui_win32")
    set guifont=Consolas:h12:cANSI
  elseif has("gui_gtk2")
    set guifont=Consolas\ 12
  endif

  " Make the window wider and higher.
  set columns=110
  set lines=31

  " Code needs room to breathe, especially if the convention is to ues
  " Egyptian brackets. Add more space between the lines.
  set linespace=4

  " Backspace behaves odd in gVim. Fix that.
  set backspace=2

  " Remove the menu bar and toolbar.
  set guioptions-=m
  set guioptions-=T
endif
