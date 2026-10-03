# immich-wallpaper

Rotates the GNOME wallpaper through the landscape photos of one Immich album. Terms are defined in [CONTEXT.md](CONTEXT.md).

- **Sync** (`immich_wallpaper.py`, run by a systemd user unit at every login) mirrors the album's Landscape Photos (originals) into `~/Pictures/Wallpapers/Immich/`. It owns that folder: anything else in it is deleted.
- **Rotation** is done by [Variety](https://peterlevi.com/variety/), with that folder as its only source, every 5 minutes.
- **Caption**: Variety's `set_wallpaper` script calls `immich-wallpaper render`, which crops the photo to the screen and draws "City, Country · 3 September 2026" on a translucent rounded box in the bottom-right corner. Set `caption = off` in the config to show plain photos.

## Install

```sh
sudo apt install variety
./install.sh   # first run creates ~/.config/immich-wallpaper/config to fill in
```

The API key goes in `~/.config/immich-wallpaper/api-key` (mode 600).

## Use

- `immich-wallpaper sync` — sync now, e.g. after adding photos to the album.
- `journalctl --user -u immich-wallpaper-sync` — past sync logs. Being offline is logged quietly; a rejected API key or missing album also raises a desktop notification.
