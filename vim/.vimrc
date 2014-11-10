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

" Highlight column 80
set colorcolumn=80

" Highlight search results, do incremental search.
" set hlsearch -- or not, looks ugly
set incsearch

" Highlight matching brackets for 0.2 seconds.
set showmatch
set mat=2

" Detect filetypes.
filetype plugin indent on

" Enable the ruler.
set ru

" Enable syntax highlighting.
syntax enable

" Filetype specific
" =================

" I cannot get ~/vimfiles/ftplugin working, so this is the second option:
" Rust uses four-space indentation.
au FileType rust set tabstop=4 shiftwidth=4

" Disable smart indent and cindent (brackets indent) for TeX files.
au FileType tex set nosi nocindent

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

  " Use Solarized Dark.
  set background=dark
  colorscheme solarized

  " Make the window wider and higher.
  set columns=110
  set lines=31

  " Backspace behaves odd in gVim. Fix that.
  set backspace=2
endif
