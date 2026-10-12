# Spec: Rotation on the Windows desktop with three Monitors

Terms are defined in [CONTEXT.md](../../CONTEXT.md).

## Problem Statement

My Linux laptop's wallpaper rotates through the Landscape Photos of my Source Album, with a Caption saying where and when each was taken. My Windows desktop has none of this. It has three Monitors side by side: a 2560×1440 primary in the middle and a 1920×1200 on either side, sitting slightly lower. DisplayFusion currently spans one image across all three from a local folder, so the desktop shows photos I picked by hand, with no Caption, and it never sees photos I add to the album.

## Solution

The desktop gets the same Sync and the same Wallpaper Pool as the laptop, plus its own Rotation. At logon and then every 5 minutes, each of the three Monitors switches to a different photo from the Local Cache. Each photo is cropped to fill its Monitor and has its own Caption in the bottom-right corner, above any taskbar. The laptop keeps Variety for Rotation, and its look and behaviour don't change, except that the Caption is now drawn with Pillow instead of ImageMagick.

## User Stories

1. As the desktop user, I want my wallpaper to come from the same Source Album as my laptop, so that I curate one album for both machines.
2. As the desktop user, I want the desktop's Wallpaper Pool to follow the same Landscape Photo rule as the laptop's, so that both machines show the same kind of photos.
3. As the desktop user, I want each Monitor to show its own photo, so that no photo is split across the bezels or cropped down to a panorama strip.
4. As the desktop user, I want the three Monitors to show three different photos at once, so that the desktop never shows a duplicate.
5. As the desktop user with a Pool of fewer than three photos, I want the Rotation to still fill every Monitor, so that no Monitor is left blank or stale.
6. As the desktop user, I want each photo cropped from its centre to fill its Monitor exactly, so that there are no black bars and no stretching.
7. As the desktop user, I want photos with EXIF rotation to appear upright, so that portrait-shot landscape files and rotated camera files display correctly.
8. As the desktop user, I want all three Monitors to change together every 5 minutes, so that the desktop has the same pace as the laptop.
9. As the desktop user, I want a Rotation right after I log on, so that I don't keep the previous session's wallpaper for the first 5 minutes.
10. As the desktop user, I want each Monitor's Caption to describe the photo on that Monitor, so that I know where and when each photo was taken.
11. As the desktop user, I want the Caption in the bottom-right corner of each Monitor's usable area, so that DisplayFusion's taskbars on the side Monitors never cover it.
12. As the desktop user, I want the Caption to keep the laptop's style (white text on a translucent rounded dark box), so that both machines look like the same tool.
13. As the desktop user, I want the Caption in Segoe UI, so that it looks native on Windows.
14. As the desktop user, I want the Caption sized relative to each Monitor's height, so that it looks the same size on the 1440- and 1200-pixel-tall Monitors.
15. As the desktop user, I want `caption = off` to show the cropped photos without text, so that I can turn Captions off the same way as on the laptop.
16. As the desktop user, I want a photo without a known date or place to be shown without a Caption, so that I never see an empty box.
17. As the desktop user, I want the Rotation to pick up changes to the Monitor layout (a Monitor unplugged, a new resolution, a moved taskbar) at the next Rotation, so that I never have to reconfigure anything.
18. As the desktop user, I want a Sync at every logon, so that photos I add to or remove from the album reach the desktop.
19. As the desktop user, I want `immich-wallpaper sync` to run a Sync now and show its log, so that a newly added photo can show up straight away.
20. As the desktop user, I want the Sync to keep the Local Cache as it is when Immich is unreachable, so that being offline never empties my wallpapers.
21. As the desktop user, I want a Windows notification when the API key is rejected or the album is gone, so that I notice problems that won't fix themselves.
22. As the desktop user, I want being offline to be logged quietly, without a notification, so that I'm not bothered by expected network blips at logon.
23. As the desktop user, I want past Sync and Rotation logs in a log file, so that I can find out what went wrong after the fact.
24. As the desktop user, I want no console window flashing up every 5 minutes, so that the Rotation is invisible.
25. As the desktop user, I want a failed Rotation (a photo deleted mid-Sync, an unreadable file) to leave that Monitor's wallpaper as it was, so that a bad photo never blanks a Monitor.
26. As the desktop user, I want an empty Local Cache (before the first successful Sync) to leave the wallpaper alone, so that installing offline doesn't break anything.
27. As the desktop user, I want my config and API key in my Windows roaming profile, so that they sit where Windows apps keep their settings.
28. As the desktop user, I want the Local Cache under my Pictures folder, as on the laptop, so that I can browse it.
29. As the desktop user, I want the desktop to use its own Immich API key, so that I can revoke one machine's access without breaking the other.
30. As the desktop user, I want one PowerShell installer that's safe to re-run, so that setting up or repairing the desktop is one command.
31. As the desktop user, I want the installer to install Pillow for me, so that I don't have to manage Python packages myself.
32. As the desktop user, I want the installer to create the config from the example and stop until I've filled it in, so that I never run with placeholder values.
33. As the desktop user, I want the installer to refuse to continue while DisplayFusion's wallpaper feature is on, so that two programs don't fight over the wallpaper.
34. As the desktop user, I want the installer to register the Sync and the Rotation as scheduled tasks, so that both run without me.
35. As the desktop user, I want an `immich-wallpaper` command available from any terminal, so that I use the same commands as on the laptop.
36. As the desktop user, I want the installer to finish with a Sync and a Rotation, so that I see the result immediately.
37. As the laptop user, I want my laptop to keep working exactly as it does now (Variety, Captions, Sync at login), so that adding the desktop costs me nothing on the laptop.
38. As the laptop user, I want `install.sh` to make sure Pillow is installed, so that the Caption still renders after the switch away from ImageMagick.
39. As the laptop user, I want the Caption still drawn in the upright Regular Ubuntu font, so that the earlier italic bug doesn't come back.
40. As the maintainer, I want one script for both machines, so that the Sync and the Wallpaper Pool rules can't drift apart.
41. As the maintainer, I want the operating-system-specific parts kept apart from the Sync, Pool and Caption logic, so that I can reason about each machine separately.
42. As the maintainer, I want tests for the code that turns photos into each Monitor's wallpaper, so that changes to cropping, Caption placement and photo choice are checked without a real desktop.

## Implementation Decisions

**One script, platform parts kept apart.** The existing single Python script stays the only program. The Sync, the Wallpaper Pool rules and the Caption text are shared and unchanged. Each operating system gets its own small adapter for:
- where files live
- how Monitors are read
- how wallpapers are set
- how notifications are raised
- how a Sync is triggered and its log shown

**Pillow replaces ImageMagick on both machines.** All image work goes through Pillow: decoding (using JPEG draft mode for speed, as the current ImageMagick size hint does), EXIF auto-orientation, centre crop-to-fill, and drawing the Caption box and text. This removes the ImageMagick text escaping and the external `convert`/`magick` program. The album holds only JPEG/PNG, so Pillow needs no extra format support.

**Monitor model.** A Monitor is described by:
- its pixel size
- its usable area (the part not covered by taskbars)

It is read fresh at every Rotation. On the laptop, the Variety hook builds a single Monitor from the largest connected screen, as it does today, with the whole screen counted as usable.

**The shared core (the test seam).** One function takes Monitors and photos with their Captions and returns one finished image per Monitor, plus a function that chooses the photos:
- **Photo choice:** distinct random photos from the Local Cache, one per Monitor. When the Pool has fewer photos than there are Monitors, repeats fill the rest. Choices are random and may repeat across Rotations, consistent with the glossary.
- **Rendering:** the photo is centre-cropped to the Monitor's pixel size. If there is Caption text and Captions are on, the Caption box is drawn at the bottom right of the usable area, inset by the existing margin.
- **Caption style:** font size, margin, padding, radius and box colour stay as they are today. They are defined for a 1080-pixel-tall Monitor and scaled by each Monitor's height.

**Linux path.** Variety's `set_wallpaper` hook and the `render` command keep their current contract: given the Local Cache photo, print the path of the image to show, or the photo itself on any failure. Internally it calls the shared core with one Monitor. Fonts: the Ubuntu font, with the upright Regular instance selected, because Ubuntu 24.04 ships it as a variable font. `install.sh` checks for `python3-pil` the same way it checks for Variety, and stops with the apt command to run if it's missing.

**Windows Rotation.** A new `rotate` command:
1. reads the Monitors
2. chooses photos
3. renders one image per Monitor into the render folder, with a fresh file name per Rotation so Windows reloads it
4. sets each Monitor's wallpaper
5. deletes the previous Rotation's images

Wallpapers are set per Monitor with the Windows per-monitor wallpaper interface (`IDesktopWallpaper`), with the position set to Fill. The image already matches the Monitor exactly, so Fill only guards against rounding. Usable areas come from the standard Windows monitor information. The process must be per-monitor DPI aware so that every size is in physical pixels. These Windows calls use Python's standard library (ctypes): Pillow is the only third-party dependency. If one Monitor fails, it keeps its current wallpaper and the others still change. An empty Local Cache means no change at all.

**Windows Sync.** The existing Sync runs unchanged, with Windows paths. `immich-wallpaper sync` runs a Sync in its own process and writes to both the console and the log file. The scheduled Sync writes only to the log file. "Unreachable" and "broken" keep their current meaning. A broken Sync raises a standard Windows notification through PowerShell, with nothing extra to install.

**Windows locations:**
- Config and API key: the roaming application-data folder
- Local Cache: under Pictures, in the same relative place as on the laptop
- Captions file, rendered wallpapers and the log file: the local application-data folder

The config format and keys are the same as on the laptop.

**Windows scheduling.** There are two per-user scheduled tasks. Both run only while the user is logged on, run under the windowless Python interpreter, and don't start a second instance while one is running:
- **Sync:** at logon.
- **Rotation:** at logon, then every 5 minutes, indefinitely.

**Windows installer (`install.ps1`, safe to re-run).** It:
1. checks for Python
2. installs Pillow for the user
3. creates the config from the example and stops until it's filled in
4. stops until the API key file exists
5. stops with instructions while DisplayFusion's wallpaper feature is on. It only reads DisplayFusion's settings and never changes them.
6. registers or updates both scheduled tasks
7. puts an `immich-wallpaper` command shim in a per-user folder that's already on PATH
8. runs a Sync and then a Rotation

**Glossary.** CONTEXT.md now covers both machines and defines **Monitor**. Rotation and Caption are defined per Monitor, and Variety is no longer mentioned.

## Testing Decisions

- **One seam: the shared core.** Tests call the function that takes Monitors and photos with their Captions and returns each Monitor's image, plus the photo-choice function. Nothing that touches the operating system is tested: reading Monitors, setting wallpapers, scheduled tasks, notifications, gsettings or Variety. Those adapters are kept too thin to need tests.
- **Test only external behaviour:** output dimensions, which photo went to which Monitor, and where the Caption box's pixels are. Never check how Pillow was called.
- **Fixtures are generated in the test:**
  - small solid-colour or patterned images, including one with an EXIF orientation that rotates it
  - made-up Monitor layouts: the desktop's three Monitors with taskbars on the two side ones, and a single laptop screen
- **Cases:**
  - each output is exactly its Monitor's pixel size
  - the centre of the photo stays in the centre after cropping, both for a photo wider than the Monitor and for one taller than it
  - EXIF orientation is applied before cropping
  - three Monitors get three different photos when the Pool has at least three, and every Monitor still gets a photo when it has fewer
  - the Caption box lies within the usable area, at its bottom-right inset, and on a side Monitor it is above the taskbar band
  - with Captions off, or with an empty Caption, no box is drawn
- **No Sync seam.** The Sync's behaviour doesn't change, so it gets no tests in this work.
- **Prior art:** none. These are the repo's first tests, using the standard library's `unittest` so nothing more needs installing.

## Out of Scope

- Replacing Variety on the laptop with our own Rotation, which would also need GNOME's spanned wallpaper for multi-monitor setups.
- One photo spanned across several Monitors.
- Syncing anywhere other than at logon or on demand (no daily or on-wake Sync).
- HEIC, RAW and any format Pillow can't read without plugins.
- A tray icon, or "previous", "pause" or "favourite" controls. On Windows, `immich-wallpaper rotate` serves as "next".
- The Windows lock screen.
- Changing DisplayFusion's settings automatically.
- Separate Source Albums or different Landscape Photo rules per machine.

## Further Notes

- DisplayFusion's current wallpaper slideshow (a local camera folder) ends when its wallpaper feature is turned off. Its taskbars and other features stay.
- The current desktop layout, for reference: left 1920×1200 at (−1920, 236), centre 2560×1440 primary at (0, 0), right 1920×1200 at (2560, 236). The side Monitors lose their bottom 48 px to DisplayFusion's taskbars.
- Windows has a built-in, unrelated `convert.exe`. Moving to Pillow avoids it entirely.
- One ADR was considered, "Windows uses our own Rotation, not DisplayFusion's slideshow", but hasn't been written.
