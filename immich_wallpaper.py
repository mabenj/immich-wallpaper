#!/usr/bin/env python3
"""Keep a local folder in exact agreement with the landscape photos of an Immich album.

Variety rotates the desktop wallpaper through that folder. See CONTEXT.md for the terms.

Usage:
    immich-wallpaper sync           Run a Sync through systemd and show its log.
    immich-wallpaper run-sync       Perform the Sync in this process (what the systemd unit runs).
    immich-wallpaper render PHOTO   Print the path of PHOTO with its Caption drawn on it
                                    (what Variety's set_wallpaper script calls).
"""

import configparser
import json
import logging
import os
import shutil
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "immich-wallpaper"
CONFIG_FILE = CONFIG_DIR / "config"
API_KEY_FILE = CONFIG_DIR / "api-key"
SERVICE = "immich-wallpaper-sync.service"
CAPTIONS_FILE = Path.home() / ".local" / "share" / "immich-wallpaper" / "captions.json"
RENDER_DIR = Path.home() / ".cache" / "immich-wallpaper"
RENDER_PREFIX = "wallpaper-"

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# Caption look, sized for a 1080 px tall screen and scaled to the actual one.
CAPTION_FONT = "Ubuntu"
CAPTION_SIZE = 15
CAPTION_MARGIN = 30
FALLBACK_SCREEN = (1920, 1080)

# At login the network is often not up yet, so keep trying for a while before giving up quietly.
CONNECT_ATTEMPTS = 12
CONNECT_RETRY_SECONDS = 10

# EXIF orientations 5-8 rotate the image by 90°, swapping its displayed width and height.
ROTATED_ORIENTATIONS = {"5", "6", "7", "8"}

log = logging.getLogger("immich-wallpaper")


class Unreachable(Exception):
    """The server could not be reached; the Local Cache is left as it is."""


class Broken(Exception):
    """A failure that will not fix itself and needs the user's attention."""


def load_config():
    config = configparser.ConfigParser()
    if not config.read(CONFIG_FILE):
        raise Broken(f"Missing config file {CONFIG_FILE}")
    try:
        api_key = API_KEY_FILE.read_text().strip()
    except OSError:
        raise Broken(f"Missing API key file {API_KEY_FILE}")
    return {
        "url": config["immich"]["url"].rstrip("/"),
        "album_id": config["immich"]["album_id"],
        "folder": Path(config["wallpaper"]["folder"]).expanduser(),
        "min_aspect_ratio": config["wallpaper"].getfloat("min_aspect_ratio", 1.3),
        "caption": config["wallpaper"].getboolean("caption", True),
        "api_key": api_key,
    }


def request(cfg, path, timeout):
    req = urllib.request.Request(
        cfg["url"] + path,
        headers={"x-api-key": cfg["api_key"], "Accept": "application/json"},
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Broken(f"Immich rejected the API key (HTTP {e.code})")
        if e.code in (400, 404):
            raise Broken(f"Immich could not find {path} (HTTP {e.code}); was the album deleted?")
        raise Unreachable(f"HTTP {e.code} from {path}")
    except (urllib.error.URLError, OSError) as e:
        raise Unreachable(str(e))


def fetch_album(cfg):
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            with request(cfg, f"/api/albums/{cfg['album_id']}", timeout=30) as resp:
                return json.load(resp)
        except Unreachable as e:
            if attempt == CONNECT_ATTEMPTS:
                raise
            log.info("Server unreachable (%s), retrying in %ss", e, CONNECT_RETRY_SECONDS)
            time.sleep(CONNECT_RETRY_SECONDS)


def displayed_size(asset):
    exif = asset.get("exifInfo") or {}
    width = exif.get("exifImageWidth") or asset.get("width")
    height = exif.get("exifImageHeight") or asset.get("height")
    if not width or not height:
        return None
    if str(exif.get("orientation")) in ROTATED_ORIENTATIONS:
        width, height = height, width
    return width, height


def cache_name(asset):
    suffix = Path(asset.get("originalFileName", "")).suffix.lower() or ".jpg"
    return asset["id"] + suffix


def caption(asset):
    """'City, Country · 3 September 2026', or only the date when the place is unknown."""
    exif = asset.get("exifInfo") or {}
    # Immich's localDateTime is already the local time where the photo was taken.
    taken = asset.get("localDateTime") or exif.get("dateTimeOriginal") or ""
    parts = []
    place = ", ".join(p for p in (exif.get("city"), exif.get("country")) if p)
    if place:
        parts.append(place)
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", taken)
    if match:
        year, month, day = (int(g) for g in match.groups())
        parts.append(f"{day} {MONTHS[month - 1]} {year}")
    return " · ".join(parts)


def wallpaper_pool(album, min_aspect_ratio):
    """Map Local Cache file names to the album's asset for every Landscape Photo."""
    assets = album.get("assets") or []
    if album.get("assetCount", 0) > 0 and not assets:
        # Guard against an Immich API change emptying the Local Cache.
        raise Broken("Immich returned the album without its photos; the API may have changed")
    pool = {}
    for asset in assets:
        if asset.get("type") != "IMAGE" or asset.get("isTrashed"):
            continue
        size = displayed_size(asset)
        if size is None:
            log.warning("Skipping %s: dimensions unknown", asset.get("originalFileName"))
            continue
        width, height = size
        if width / height >= min_aspect_ratio:
            pool[cache_name(asset)] = asset
    return pool


def download(cfg, asset_id, target):
    part = target.with_name("." + target.name + ".part")
    try:
        with request(cfg, f"/api/assets/{asset_id}/original", timeout=120) as resp, open(part, "wb") as f:
            shutil.copyfileobj(resp, f)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def sync(cfg):
    folder = cfg["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    pool = wallpaper_pool(fetch_album(cfg), cfg["min_aspect_ratio"])

    # The Local Cache holds nothing but the pool: anything else in the folder goes.
    removed = 0
    for path in folder.iterdir():
        if path.is_file() and path.name not in pool:
            path.unlink()
            removed += 1

    missing = [name for name in pool if not (folder / name).exists()]
    for i, name in enumerate(missing, 1):
        log.info("Downloading %d/%d: %s", i, len(missing), name)
        download(cfg, pool[name]["id"], folder / name)

    # Rewritten every Sync so corrections made in Immich reach the Captions.
    write_json(CAPTIONS_FILE, {name: caption(asset) for name, asset in pool.items()})

    log.info("Wallpaper Pool has %d photos: %d added, %d removed", len(pool), len(missing), removed)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(f.name, path)


def screen_size():
    """The largest connected screen, as GNOME's zoom would fill it."""
    try:
        out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=5).stdout
        sizes = [tuple(map(int, m)) for m in re.findall(r"^\s+(\d+)x(\d+)\S*\s.*\*", out, re.M)]
    except (OSError, subprocess.SubprocessError):
        sizes = []
    return max(sizes, default=FALLBACK_SCREEN, key=lambda s: s[0] * s[1])


def magick_text(text):
    # ImageMagick reads a leading '@' as a file name and expands '%' escapes.
    return text.replace("\\", "\\\\").replace("%", "%%").lstrip("@")


def draw_caption(photo, text, target):
    width, height = screen_size()
    size = round(CAPTION_SIZE * height / 1080)
    margin = round(CAPTION_MARGIN * height / 1080)
    style = ["-font", CAPTION_FONT, "-pointsize", str(size), "-gravity", "SouthEast"]
    annotate = ["-annotate", f"+{margin}+{margin}", magick_text(text)]
    subprocess.run(
        [
            "convert", "-define", f"jpeg:size={width * 2}x{height * 2}", str(photo), "-auto-orient",
            # Fill the screen and crop the centre, exactly as GNOME's zoom would.
            "-resize", f"{width}x{height}^", "-gravity", "center", "-extent", f"{width}x{height}",
            # A blurred dark copy of the text keeps it readable on bright skies.
            "(", "-size", f"{width}x{height}", "xc:none", *style, "-fill", "rgba(0,0,0,0.8)",
            *annotate, "-blur", f"0x{max(2, size // 5)}", ")", "-composite",
            *style, "-fill", "white", *annotate,
            "-quality", "92", str(target),
        ],
        check=True,
        timeout=60,
        capture_output=True,
    )


def render(photo):
    """Return the image to show for PHOTO: a screen-sized copy with its Caption, or PHOTO itself."""
    photo = Path(photo)
    try:
        if not load_config()["caption"]:
            return photo
        text = json.loads(CAPTIONS_FILE.read_text(encoding="utf-8")).get(photo.name)
    except (Broken, OSError, ValueError) as e:
        log.warning("No Caption for %s: %s", photo.name, e)
        return photo
    if not text:
        return photo
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    # A fresh file name per photo makes GNOME reload the wallpaper.
    target = RENDER_DIR / f"{RENDER_PREFIX}{photo.stem}.jpg"
    part = RENDER_DIR / f".{target.name}.part.jpg"
    try:
        draw_caption(photo, text, part)
        os.replace(part, target)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Could not draw the Caption on %s: %s", photo.name, e)
        part.unlink(missing_ok=True)
        return photo
    for old in RENDER_DIR.glob(RENDER_PREFIX + "*"):
        if old != target:
            old.unlink(missing_ok=True)
    return target


def notify(message):
    try:
        subprocess.run(
            ["notify-send", "--icon=dialog-warning", "Immich wallpaper sync failed", message],
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def run_sync():
    try:
        sync(load_config())
    except Unreachable as e:
        log.info("Immich unreachable, keeping the Local Cache as it is: %s", e)
    except Broken as e:
        log.error("%s", e)
        notify(str(e))
        return 1
    return 0


def sync_via_systemd():
    started = subprocess.run(["systemctl", "--user", "start", SERVICE])
    invocation = subprocess.run(
        ["systemctl", "--user", "show", "--property=InvocationID", "--value", SERVICE],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if invocation:
        subprocess.run(["journalctl", "--user", "--output=cat", f"_SYSTEMD_INVOCATION_ID={invocation}"])
    return started.returncode


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) == 3 and argv[1] == "render":
        print(render(argv[2]))
        return 0
    commands = {"sync": sync_via_systemd, "run-sync": run_sync}
    if len(argv) != 2 or argv[1] not in commands:
        print(__doc__.strip().split("\n\n", 2)[2], file=sys.stderr)
        return 2
    return commands[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
