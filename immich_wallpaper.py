#!/usr/bin/env python3
"""Keep a local folder in exact agreement with the landscape photos of an Immich album.

On Linux Variety rotates the desktop wallpaper through that folder; on Windows `rotate` does.
See CONTEXT.md for the terms.

Usage:
    immich-wallpaper sync           Run a Sync and show its log (on Linux, through systemd).
    immich-wallpaper run-sync       Perform the Sync in this process (what the systemd unit or scheduled task runs).
    immich-wallpaper rotate         Windows: give each Monitor another photo (what the scheduled task runs).
    immich-wallpaper render PHOTO   Linux: print the path of PHOTO with its Caption drawn on it
                                    (what Variety's set_wallpaper script calls).
"""

import configparser
import ctypes
import json
import logging
import logging.handlers
import os
import random
import shutil
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import namedtuple
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

WINDOWS = sys.platform == "win32"
if WINDOWS:
    CONFIG_DIR = Path(os.environ["APPDATA"]) / "immich-wallpaper"
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "immich-wallpaper"
    CAPTIONS_FILE = DATA_DIR / "captions.json"
    RENDER_DIR = DATA_DIR / "wallpapers"
    LOG_FILE = DATA_DIR / "immich-wallpaper.log"
    CAPTION_FONT = "segoeui.ttf"
else:
    CONFIG_DIR = Path.home() / ".config" / "immich-wallpaper"
    CAPTIONS_FILE = Path.home() / ".local" / "share" / "immich-wallpaper" / "captions.json"
    RENDER_DIR = Path.home() / ".cache" / "immich-wallpaper"
    CAPTION_FONT = "Ubuntu-R.ttf"
CONFIG_FILE = CONFIG_DIR / "config"
API_KEY_FILE = CONFIG_DIR / "api-key"
SERVICE = "immich-wallpaper-sync.service"
RENDER_PREFIX = "wallpaper-"

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# Caption look, sized for a 1080 px tall Monitor and scaled to the actual one.
CAPTION_SIZE = 15
CAPTION_MARGIN = 30
CAPTION_PADDING = (12, 4)  # horizontal, vertical
CAPTION_RADIUS = 9
CAPTION_BOX_COLOR = (0, 0, 0, 115)  # 45% opaque
CAPTION_SUPERSAMPLING = 4
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


def request(cfg, path, timeout, body=None):
    headers = {"x-api-key": cfg["api_key"], "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(cfg["url"] + path, data=data, headers=headers)
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
                album = json.load(resp)
            album["assets"] = fetch_album_assets(cfg)
            return album
        except Unreachable as e:
            if attempt == CONNECT_ATTEMPTS:
                raise
            log.info("Server unreachable (%s), retrying in %ss", e, CONNECT_RETRY_SECONDS)
            time.sleep(CONNECT_RETRY_SECONDS)


def fetch_album_assets(cfg):
    # Since Immich 3 the album itself no longer lists its assets.
    assets, page = [], 1
    while page:
        query = {"albumIds": [cfg["album_id"]], "withExif": True, "size": 1000, "page": page}
        with request(cfg, "/api/search/metadata", timeout=60, body=query) as resp:
            result = json.load(resp)["assets"]
        assets.extend(result["items"])
        page = result["nextPage"]
    return assets


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


# usable is (left, top, right, bottom) in the Monitor's own pixels: the part no taskbar covers.
Monitor = namedtuple("Monitor", "width height usable")


def choose_photos(photos, count):
    """COUNT different random photos, repeating some only when there are fewer than COUNT."""
    chosen = random.sample(photos, min(count, len(photos)))
    return chosen + random.choices(photos, k=count - len(chosen))


# Pillow refuses images this large as possible decompression bombs, but panoramas from the Source Album are trusted.
Image.MAX_IMAGE_PIXELS = None


def wallpaper(photo, text, monitor):
    """PHOTO cropped to fill MONITOR, as GNOME's zoom would, with the Caption TEXT drawn on it."""
    with Image.open(photo) as image:
        # Decoding a large JPEG at a reduced scale is much faster and loses nothing at Monitor size.
        image.draft("RGB", (monitor.width * 2, monitor.height * 2))
        image = ImageOps.fit(ImageOps.exif_transpose(image), (monitor.width, monitor.height), Image.LANCZOS)
    if text:
        image = draw_caption(image, text, monitor)
    return image.convert("RGB")


def draw_caption(image, text, monitor):
    # Drawn larger and scaled down, so the box's rounded corners and the text's edges come out smooth.
    scale = monitor.height / 1080 * CAPTION_SUPERSAMPLING
    font = ImageFont.truetype(CAPTION_FONT, round(CAPTION_SIZE * scale))
    ascent, descent = font.getmetrics()
    padding_x, padding_y = (round(p * scale) for p in CAPTION_PADDING)
    width, height = round(font.getlength(text)) + 2 * padding_x, ascent + descent + 2 * padding_y
    # A translucent rounded box behind the text keeps it readable on any background.
    box = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(box)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), round(CAPTION_RADIUS * scale), fill=CAPTION_BOX_COLOR)
    draw.text((padding_x, padding_y), text, font=font, fill="white")
    box = box.resize((round(width / CAPTION_SUPERSAMPLING), round(height / CAPTION_SUPERSAMPLING)), Image.LANCZOS)
    margin = round(CAPTION_MARGIN * monitor.height / 1080)
    image = image.convert("RGBA")
    image.alpha_composite(box, (monitor.usable[2] - margin - box.width, monitor.usable[3] - margin - box.height))
    return image


def screen_size():
    """The largest connected screen, as GNOME's zoom would fill it."""
    try:
        out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=5).stdout
        sizes = [tuple(map(int, m)) for m in re.findall(r"^\s+(\d+)x(\d+)\S*\s.*\*", out, re.M)]
    except (OSError, subprocess.SubprocessError):
        sizes = []
    return max(sizes, default=FALLBACK_SCREEN, key=lambda s: s[0] * s[1])


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
    width, height = screen_size()
    try:
        wallpaper(photo, text, Monitor(width, height, (0, 0, width, height))).save(part, "JPEG", quality=92)
        os.replace(part, target)
    except (OSError, ValueError) as e:
        log.warning("Could not draw the Caption on %s: %s", photo.name, e)
        part.unlink(missing_ok=True)
        return photo
    for old in RENDER_DIR.glob(RENDER_PREFIX + "*"):
        if old != target:
            old.unlink(missing_ok=True)
    return target


class DesktopWallpaper:
    """Windows' IDesktopWallpaper, which gives each Monitor its own wallpaper."""

    CLSID = "{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}"
    IID = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
    CLSCTX_ALL = 0x17
    FILL = 4
    # Positions of the interface's methods in its vtable.
    SET_WALLPAPER, GET_WALLPAPER, GET_MONITOR_DEVICE_PATH_AT, GET_MONITOR_DEVICE_PATH_COUNT, GET_MONITOR_RECT = 3, 4, 5, 6, 7
    SET_POSITION = 10

    def __init__(self):
        ole32 = ctypes.oledll.ole32
        ole32.CoInitialize(None)
        clsid, iid = ctypes.create_string_buffer(16), ctypes.create_string_buffer(16)
        ole32.CLSIDFromString(self.CLSID, clsid)
        ole32.CLSIDFromString(self.IID, iid)
        self.com = ctypes.c_void_p()
        ole32.CoCreateInstance(clsid, None, self.CLSCTX_ALL, iid, ctypes.byref(self.com))

    def call(self, index, *args):
        """Call the method at INDEX in the interface's vtable; a failure HRESULT raises OSError."""
        vtable = ctypes.cast(self.com, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *(type(a) for a in args))(vtable[index])
        method(self.com, *args)

    def call_for_string(self, index, *args):
        """Call a method whose last parameter receives a string, and return that string."""
        out = ctypes.c_void_p()
        self.call(index, *args, ctypes.pointer(out))
        try:
            return ctypes.wstring_at(out.value) if out.value else ""
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)

    def monitors(self):
        """The id and the Monitor of each attached Monitor."""
        count = ctypes.c_uint()
        self.call(self.GET_MONITOR_DEVICE_PATH_COUNT, ctypes.pointer(count))
        monitors = []
        for i in range(count.value):
            monitor_id = self.call_for_string(self.GET_MONITOR_DEVICE_PATH_AT, ctypes.c_uint(i))
            rect = wintypes.RECT()
            try:
                self.call(self.GET_MONITOR_RECT, ctypes.c_wchar_p(monitor_id), ctypes.pointer(rect))
            except OSError:
                continue  # The id of a Monitor that is not attached.
            if rect.right > rect.left:
                monitors.append((monitor_id, Monitor(rect.right - rect.left, rect.bottom - rect.top, usable_area(rect))))
        return monitors

    def get(self, monitor_id):
        return self.call_for_string(self.GET_WALLPAPER, ctypes.c_wchar_p(monitor_id))

    def set(self, monitor_id, path):
        self.call(self.SET_POSITION, ctypes.c_int(self.FILL))
        self.call(self.SET_WALLPAPER, ctypes.c_wchar_p(monitor_id), ctypes.c_wchar_p(str(path)))


MONITOR_DEFAULTTONEAREST = 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def usable_area(rect):
    """The part of the Monitor at RECT that no taskbar covers, in the Monitor's own pixels."""
    user32 = ctypes.windll.user32
    user32.MonitorFromRect.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(MONITORINFO))
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    work = info.rcWork
    return work.left - rect.left, work.top - rect.top, work.right - rect.left, work.bottom - rect.top


def rotate():
    """Give each Monitor a different photo from the Local Cache, with its Caption."""
    # Without this, Windows reports scaled-down sizes for Monitors with display scaling.
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    try:
        cfg = load_config()
    except Broken as e:
        log.error("%s", e)
        return 1
    photos = [p for p in cfg["folder"].glob("*") if p.is_file() and not p.name.startswith(".")]
    if not photos:
        log.info("The Local Cache is empty; keeping the wallpaper as it is")
        return 0
    captions = {}
    if cfg["caption"]:
        try:
            captions = json.loads(CAPTIONS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("No Captions: %s", e)
    try:
        desktop = DesktopWallpaper()
        monitors = desktop.monitors()
    except OSError as e:
        log.error("Could not read the Monitors: %s", e)
        return 1
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    # A fresh file name per Rotation makes Windows reload the wallpaper.
    stamp = time.strftime("%Y%m%d%H%M%S")
    chosen = choose_photos(photos, len(monitors))
    log.info("Rotation on %d Monitors: %s", len(monitors), ", ".join(
        f"Monitor {i + 1} ({monitor.width}×{monitor.height}) ← {photo.name}"
        for i, ((_, monitor), photo) in enumerate(zip(monitors, chosen))))
    for i, ((monitor_id, monitor), photo) in enumerate(zip(monitors, chosen)):
        target = RENDER_DIR / f"{RENDER_PREFIX}{stamp}-{i}.jpg"
        try:
            wallpaper(photo, captions.get(photo.name, ""), monitor).save(target, "JPEG", quality=92)
            desktop.set(monitor_id, target)
        except (OSError, ValueError) as e:
            log.warning("Keeping the wallpaper of Monitor %d as it is: %s", i + 1, e)
    try:
        shown = {Path(desktop.get(monitor_id)).name for monitor_id, _ in monitors}
    except OSError as e:
        log.warning("Keeping old wallpapers, as the shown ones are unknown: %s", e)
        return 0
    for old in RENDER_DIR.glob(RENDER_PREFIX + "*"):
        if old.name not in shown:
            old.unlink(missing_ok=True)
    return 0


# Reads the message from the environment so that no quoting can break the script.
WINDOWS_NOTIFICATION = r"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('ToastText02')
$text = $xml.GetElementsByTagName('text')
$null = $text.Item(0).AppendChild($xml.CreateTextNode('Immich wallpaper sync failed'))
$null = $text.Item(1).AppendChild($xml.CreateTextNode($env:IMMICH_WALLPAPER_MESSAGE))
$powershell = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($powershell).Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify(message):
    if WINDOWS:
        command = dict(
            args=["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_NOTIFICATION],
            env={**os.environ, "IMMICH_WALLPAPER_MESSAGE": message},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        command = dict(args=["notify-send", "--icon=dialog-warning", "Immich wallpaper sync failed", message])
    try:
        subprocess.run(**command, timeout=10)
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
    # Under pythonw (the scheduled tasks) there is no stderr.
    handlers = [logging.StreamHandler()] if sys.stderr else []
    if WINDOWS:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=1,
                                                             encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s" if WINDOWS else "%(message)s",
                        handlers=handlers)
    if len(argv) == 3 and argv[1] == "render":
        print(render(argv[2]))
        return 0
    if WINDOWS:
        commands = {"sync": run_sync, "run-sync": run_sync, "rotate": rotate}
    else:
        commands = {"sync": sync_via_systemd, "run-sync": run_sync}
    if len(argv) != 2 or argv[1] not in commands:
        print(__doc__.strip().split("\n\n", 2)[2], file=sys.stderr)
        return 2
    return commands[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
