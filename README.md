# immich-wallpaper

Rotates the wallpaper of a GNOME laptop and a multi-Monitor Windows desktop through the landscape photos of one Immich album. Terms are defined in [CONTEXT.md](CONTEXT.md).

- **Sync** (`immich_wallpaper.py`, run at every login) mirrors the album's Landscape Photos (originals) into `~/Pictures/Wallpapers/Immich/`. It owns that folder: anything else in it is deleted.
- **Rotation**, every 5 minutes:
  - Linux: [Variety](https://peterlevi.com/variety/), with that folder as its only source.
  - Windows: `immich-wallpaper rotate`, which gives each Monitor a different photo.
- **Caption**: each photo is cropped to its Monitor, with "City, Country · 3 September 2026" drawn on a translucent rounded box in the bottom-right corner, above any taskbar. On Linux, Variety's `set_wallpaper` script calls `immich-wallpaper render` to do this. Set `caption = off` in the config to show plain photos.

## Install

Linux:

```sh
sudo apt install variety python3-pil
./install.sh   # first run creates ~/.config/immich-wallpaper/config to fill in
```

The API key goes in `~/.config/immich-wallpaper/api-key` (mode 600).

Windows: turn off DisplayFusion's wallpaper feature if you use it, then

```powershell
.\install.ps1   # first run creates %APPDATA%\immich-wallpaper\config to fill in
```

The API key goes in `%APPDATA%\immich-wallpaper\api-key`. Give each machine its own key.

## Use

- `immich-wallpaper sync`: sync now, e.g. after adding photos to the album.
- `immich-wallpaper rotate` (Windows): show other photos now.
- Past logs:
  - Linux: `journalctl --user -u immich-wallpaper-sync`.
  - Windows: `%LOCALAPPDATA%\immich-wallpaper\immich-wallpaper.log`.

  Being offline is logged quietly; a rejected API key or missing album also raises a desktop notification.
- Tests: `python -m unittest test_immich_wallpaper`.
