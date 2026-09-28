import json
import tempfile
import unittest
from pathlib import Path

from collector import core


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (core.DATA_DIR, core.DB_PATH, core.MEDIA_DIR, core.EXPORT_DIR)
        core.DATA_DIR = Path(self.tmp.name) / "data"
        core.DB_PATH = core.DATA_DIR / "collection.db"
        core.MEDIA_DIR = core.DATA_DIR / "media"
        core.EXPORT_DIR = core.DATA_DIR / "exports"

    def tearDown(self):
        core.DATA_DIR, core.DB_PATH, core.MEDIA_DIR, core.EXPORT_DIR = self.old
        self.tmp.cleanup()

    def test_import_classifies_and_dedupes(self):
        rows = [{"reel_url": "https://www.instagram.com/reel/abc/", "username": "creator", "profile_url": "https://www.instagram.com/creator/", "caption": "Live acoustic guitar cover", "source_kind": "hashtag", "source_query": "#guitarcover"}]
        first = core.import_records(rows)
        second = core.import_records(rows)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["updated"], 1)
        item = core.records()[0]
        self.assertEqual(item["performance_type"], "singing_and_instrument")
        self.assertEqual(item["instrument"], "guitar")

    def test_export_credits(self):
        core.import_records([{"reel_url": "https://www.instagram.com/reel/xyz/", "username": "artist", "profile_photo_url": "https://cdn.example/photo.jpg"}])
        path = core.export_credits("json")
        payload = json.loads(Path(path).read_text())
        self.assertEqual(payload[0]["username"], "artist")
        self.assertEqual(payload[0]["profile_photo_url"], "https://cdn.example/photo.jpg")


if __name__ == "__main__":
    unittest.main()
