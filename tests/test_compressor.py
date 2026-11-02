import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from compressor import compress_file, process_folder


class CompressorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_compressed_output_is_not_larger_and_keeps_format(self):
        source = self.root / "source.jpg"
        image = Image.new("RGB", (500, 400), "navy")
        image.save(source, format="JPEG", quality=98)
        output = self.root / "compressed.jpg"

        result = compress_file(str(source), str(output), quality=82)

        self.assertLessEqual(result["new_size"], result["original_size"])
        with Image.open(output) as compressed:
            self.assertEqual(compressed.format, "JPEG")

    def test_exif_orientation_is_applied(self):
        source = self.root / "oriented.jpg"
        image = Image.new("RGB", (80, 40), "red")
        exif = Image.Exif()
        exif[274] = 6
        image.save(source, format="JPEG", quality=95, exif=exif)
        output = self.root / "oriented_compressed.jpg"

        compress_file(str(source), str(output), quality=82)

        with Image.open(output) as compressed:
            self.assertEqual(compressed.size, (40, 80))
            self.assertEqual(compressed.getexif().get(274), None)

    def test_folder_output_preserves_tree_and_originals(self):
        source = self.root / "source"
        nested = source / "nested"
        nested.mkdir(parents=True)
        original = nested / "image.png"
        Image.new("RGB", (32, 24), "green").save(original, format="PNG")
        output = self.root / "result"

        report = process_folder(str(source), str(output))

        self.assertEqual(report["images"], 1)
        self.assertTrue(original.exists())
        self.assertTrue((output / "nested" / "image.png").exists())
        with Image.open(output / "nested" / "image.png") as compressed:
            self.assertEqual(compressed.format, "PNG")

    def test_non_image_copy_creates_nested_destination(self):
        source = self.root / "source"
        nested = source / "nested"
        nested.mkdir(parents=True)
        original = nested / "notes.txt"
        original.write_text("keep this file", encoding="utf-8")
        output = self.root / "result"

        report = process_folder(
            str(source), str(output), copy_non_images=True
        )

        self.assertEqual(report["files"], 1)
        self.assertEqual((output / "nested" / "notes.txt").read_text(encoding="utf-8"), "keep this file")
        self.assertEqual(report["original_size"], report["new_size"])


if __name__ == "__main__":
    unittest.main()
