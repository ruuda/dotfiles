" Rust's preferences deviate from my defaults, restore Rust's idioms.
set tabstop=4 shiftwidth=4

" Rust builds with Cargo, but run check as the default make command.
set makeprg=cargo\ check

" I prefer 80-column files over Rust's default 100.
set textwidth=80

" TODO: Figure out Ale language server client?
" let b:ale_fixers = ['rustfmt']
