# Gnome Settings

Gnome settings are stored in dconf. To export the current settings:

    dconf dump /org/gnome/terminal/ > gnome-terminal.conf

To restore:

    dconf load /org/gnome/terminal/ < gnome-terminal.conf
