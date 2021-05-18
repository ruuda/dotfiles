" Rust's preferences deviate from my defaults, restore Rust's idioms.
set tabstop=4 shiftwidth=4

" Rust builds with Cargo, but run check as the default make command.
set makeprg=cargo\ check

" I prefer 80-column files over Rust's default 100.
set textwidth=80

" Configure the Ale language server client and linter.
" ====================================================

" Make :ALEFix run rustfmt.
let b:ale_fixers = ['trim_whitespace', 'remove_trailing_lines', 'rustfmt']

" Enable symbol info on hover in gVim.
let g:ale_set_balloons = 1

" Use Ale's completion (needs to be set separately from
" g:ale_completion_enabled). Without this, Ctrl+N shows documentation instead
" of accepting the solution. Probably I just don't understand how omnicomplete
" works ...
set omnifunc=ale#completion#OmniFunc

" Override the default 'jump to tag' key combination with Ale's go to
" definition, the ctags one does not work with Rust anyway by default.
noremap <C-]> :ALEGoToDefinition<Return>
