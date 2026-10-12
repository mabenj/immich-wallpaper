import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from immich_wallpaper import Monitor, choose_photos, wallpaper

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


class WallpaperTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def photo(self, image, **save):
        path = Path(self.dir.name) / "photo.png"
        image.save(path, **save)
        return path

    def thirds(self, size, horizontal):
        """A photo split into red, green and blue thirds, side by side or stacked."""
        image = Image.new("RGB", size)
        width, height = size
        for i, color in enumerate((RED, GREEN, BLUE)):
            box = (i * width // 3, 0, (i + 1) * width // 3, height) if horizontal \
                else (0, i * height // 3, width, (i + 1) * height // 3)
            image.paste(color, box)
        return self.photo(image)

    def test_fills_the_monitor_with_the_centre_of_a_wider_photo(self):
        image = wallpaper(self.thirds((300, 100), horizontal=True), "", Monitor(100, 200, (0, 0, 100, 200)))
        self.assertEqual(image.size, (100, 200))
        self.assertEqual(image.convert("RGB").getcolors(), [(100 * 200, GREEN)])

    def test_fills_the_monitor_with_the_centre_of_a_taller_photo(self):
        image = wallpaper(self.thirds((100, 300), horizontal=False), "", Monitor(200, 100, (0, 0, 200, 100)))
        self.assertEqual(image.size, (200, 100))
        self.assertEqual(image.convert("RGB").getcolors(), [(200 * 100, GREEN)])

    def test_turns_the_photo_upright_before_cropping(self):
        stored = Image.new("RGB", (30, 60), BLUE)
        stored.paste(RED, (0, 0, 30, 30))
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: the stored top row is the visual right-hand side.
        image = wallpaper(self.photo(stored, exif=exif), "", Monitor(60, 30, (0, 0, 60, 30))).convert("RGB")
        self.assertEqual((image.getpixel((5, 5)), image.getpixel((55, 5))), (BLUE, RED))

    def caption_box(self, image):
        """The bounding box of everything drawn on a plain white photo."""
        return ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, WHITE)).getbbox()

    def test_draws_the_caption_in_the_bottom_right_corner_above_the_taskbar(self):
        white = self.photo(Image.new("RGB", (192, 108), WHITE))
        # A 1080 px tall Monitor whose bottom 48 px are a taskbar; the Caption keeps a 30 px margin.
        image = wallpaper(white, "Helsinki, Finland · 3 September 2026", Monitor(1920, 1080, (0, 0, 1920, 1032)))
        left, top, right, bottom = self.caption_box(image)
        self.assertEqual((right, bottom), (1890, 1002))
        self.assertLess(left, right - 200)
        self.assertLess(top, bottom - 15)

    def test_scales_the_caption_to_a_taller_side_monitor(self):
        white = self.photo(Image.new("RGB", (192, 120), WHITE))
        # A desktop side Monitor: 1200 px tall, with a 48 px taskbar; the margin scales to 33 px.
        image = wallpaper(white, "Turku, Finland · 1 May 2026", Monitor(1920, 1200, (0, 0, 1920, 1152)))
        self.assertEqual(self.caption_box(image)[2:], (1887, 1119))

    def test_draws_no_box_for_an_empty_caption(self):
        white = self.photo(Image.new("RGB", (192, 108), WHITE))
        self.assertIsNone(self.caption_box(wallpaper(white, "", Monitor(1920, 1080, (0, 0, 1920, 1032)))))


class ChoosePhotosTest(unittest.TestCase):
    def test_gives_every_monitor_a_different_photo(self):
        photos = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
        for _ in range(20):
            chosen = choose_photos(photos, 3)
            self.assertEqual(len(set(chosen)), 3)
            self.assertLessEqual(set(chosen), set(photos))

    def test_repeats_photos_only_when_there_are_fewer_than_monitors(self):
        for _ in range(20):
            chosen = choose_photos(["a.jpg", "b.jpg"], 3)
            self.assertEqual(len(chosen), 3)
            self.assertEqual(set(chosen), {"a.jpg", "b.jpg"})


if __name__ == "__main__":
    unittest.main()
