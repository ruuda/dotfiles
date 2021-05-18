" Disable smart indent and cindent (brackets indent) for TeX files. Setting
" indentexpr to empty ensures that Vim does not mess up things after typing a
" curly bracket.
au FileType tex set nosmartindent nocindent indentexpr=

" Build TeX with latexmk.
if has("win32") " The dash should not be escaped on Windows.
  au FileType tex set makeprg=latexmk\  -xelatex\ %
else
  au FileType tex set makeprg=latexmk\ \-xelatex\ %
endif

