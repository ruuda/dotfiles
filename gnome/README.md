# Gnome Settings

Gnome settings are stored in dconf. To export the current settings:

    dconf dump /org/gnome/terminal/ > gnome-terminal.conf
    dconf dump /org/gnome/shell/    > gnome-shell.conf
    dconf dump /org/gnome/nautilus/ > nautilus.conf

To restore:

    dconf load /org/gnome/terminal/ < gnome-terminal.conf
    dconf load /org/gnome/shell/    < gnome-shell.conf
    dconf load /org/gnome/nautilus/ < nautilus.conf
