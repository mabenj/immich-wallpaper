# Immich Wallpaper

Keeps the laptop's desktop wallpaper rotating through the landscape photos of one curated Immich album.

## Language

**Source Album**:
The single Immich album that defines which photos may become wallpapers; it is the only source of truth.
_Avoid_: Gallery, collection, best-of

**Landscape Photo**:
A photo whose aspect ratio, after applying its EXIF orientation, is at least 1.3 (width ÷ height); there is no upper limit, so panoramas qualify.
_Avoid_: Horizontal photo, wide photo

**Wallpaper Pool**:
The set of non-trashed Landscape Photos currently in the Source Album, regardless of archived or hidden status; photos removed from the album leave the pool.
_Avoid_: Playlist, rotation set

**Local Cache**:
The on-disk mirror of the Wallpaper Pool, holding original files, from which wallpapers are always shown; it holds nothing but the pool.
_Avoid_: Download folder, wallpaper folder

**Sync**:
Bringing the Local Cache into exact agreement with the Wallpaper Pool: adding new photos and deleting removed ones.
_Avoid_: Refresh, import, fetch

**Rotation**:
Changing the displayed wallpaper to another photo from the Local Cache, done periodically by Variety.
_Avoid_: Slideshow, cycle (Rotation picks randomly and may repeat)
