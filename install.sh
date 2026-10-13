#!/usr/bin/env bash
# Installs the Sync (command + systemd user unit) and sets up Variety for Rotation. Safe to re-run.
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
config_dir="$HOME/.config/immich-wallpaper"
variety_dir="$HOME/.config/variety"

if ! command -v variety >/dev/null; then
    echo "Variety is not installed. Run: sudo apt install variety" >&2
    exit 1
fi
if ! python3 -c 'import PIL' 2>/dev/null; then
    echo "Pillow is not installed. Run: sudo apt install python3-pil" >&2
    exit 1
fi

mkdir -p "$config_dir"
chmod 700 "$config_dir"
if [[ ! -f "$config_dir/config" ]]; then
    cp "$repo/config.example" "$config_dir/config"
    echo "Created $config_dir/config: fill in the Immich URL and album id, then re-run." >&2
    exit 1
fi
if [[ ! -s "$config_dir/api-key" ]]; then
    echo "Put an Immich API key in $config_dir/api-key (chmod 600), then re-run." >&2
    exit 1
fi
folder="$(python3 -c 'import configparser, os, sys; c = configparser.ConfigParser(); c.read(sys.argv[1]); print(os.path.expanduser(c["wallpaper"]["folder"]))' "$config_dir/config")"
mkdir -p "$folder"
minutes="$(python3 -c 'import configparser, sys; c = configparser.ConfigParser(); c.read(sys.argv[1]); print(c.get("wallpaper", "rotation_minutes", fallback="5").strip())' "$config_dir/config")"
if [[ ! "$minutes" =~ ^[0-9]+$ ]] || (( 10#$minutes < 1 )); then
    echo "rotation_minutes in $config_dir/config must be a whole number of minutes, not '$minutes'." >&2
    exit 1
fi
minutes=$((10#$minutes))

# Sync
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user"
ln -sf "$repo/immich_wallpaper.py" "$HOME/.local/bin/immich-wallpaper"
ln -sf "$repo/systemd/immich-wallpaper-sync.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable immich-wallpaper-sync.service

# Variety: configure only once, before its first start, so later changes made in its UI survive.
if [[ -f "$variety_dir/variety.conf" ]]; then
    echo "Variety is already configured; leaving $variety_dir untouched."
else
    if pgrep -x variety >/dev/null; then
        echo "Quit Variety before installing, so it doesn't overwrite the new config." >&2
        exit 1
    fi
    mkdir -p "$variety_dir/scripts" "$HOME/.config/autostart"
    sed -e "s|{FOLDER}|$folder|" -e "s|{INTERVAL}|$((minutes * 60))|" "$repo/variety/variety.conf" > "$variety_dir/variety.conf"
    # Mark the first run as done so Variety skips its welcome and preferences dialogs.
    date '+%Y-%m-%d %H:%M:%S' > "$variety_dir/.firstrun"
    dpkg-query -W -f='${Version}' variety | cut -d- -f1 > "$variety_dir/.version"
    sed -e "s|{VARIETY_PATH}|$(command -v variety)|" -e "s|{PROFILE_PATH}|$variety_dir/|" -e "s|{WM_CLASS}|Variety|" \
        /usr/share/variety/variety-autostart.desktop.template > "$HOME/.config/autostart/variety.desktop"
fi
# The interval follows rotation_minutes, even when it was changed in Variety's preferences.
interval="change_interval = $((minutes * 60))"
if ! grep -qx "$interval" "$variety_dir/variety.conf"; then
    if pgrep -x variety >/dev/null; then
        echo "Quit Variety before installing, so the new interval of $minutes minutes isn't overwritten." >&2
        exit 1
    fi
    sed -i '/^change_interval *=/d' "$variety_dir/variety.conf"
    sed -i "1i $interval" "$variety_dir/variety.conf"
fi

# Patch Variety's wallpaper script (its user copy is meant to be customised). Each patch is applied once.
script="$variety_dir/scripts/set_wallpaper"
if [[ ! -f "$script" ]]; then
    mkdir -p "$variety_dir/scripts"
    cp /usr/share/variety/scripts/set_wallpaper "$script"
    chmod +x "$script"
fi
# Variety before 0.8.12 predates GNOME 42's separate dark-mode wallpaper; set it too.
if ! grep -q 'picture-uri-dark' "$script"; then
    sed -i '/gsettings set org.gnome.desktop.background picture-uri "file:\/\/$WP"/a gsettings set org.gnome.desktop.background picture-uri-dark "file://$WP" 2> /dev/null' "$script"
fi
# Show the photo with its Caption drawn on it. Replaces an older version of this patch.
# $3 is the photo in the Local Cache: Variety 0.8.12 passes an auto-rotated copy as $1, whose name has no Caption.
sed -i '/immich-wallpaper/d' "$script"
sed -i '/^WP=\$1$/a # immich-wallpaper: draw the Caption on the photo; falls back to the photo itself.\nWP=$("$HOME/.local/bin/immich-wallpaper" render "$3" 2>/dev/null) \&\& [ -n "$WP" ] || WP=$1' "$script"

"$HOME/.local/bin/immich-wallpaper" sync

if ! pgrep -x variety >/dev/null; then
    setsid variety >/dev/null 2>&1 < /dev/null &
fi
echo "Done. Variety rotates through $folder every $minutes minutes."
