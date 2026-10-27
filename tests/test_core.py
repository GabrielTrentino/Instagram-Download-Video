import json
import tempfile
import unittest
from pathlib import Path

from insta_downloader.config import APP_ROOT, Settings
from insta_downloader.downloader import build_filename, normalize_url, parse_sources
from insta_downloader.history import HISTORY_FILENAME, History, HistoryEntry, format_size


class UrlParsingTests(unittest.TestCase):
    def test_normalize_strips_tracking_and_unifies_host(self):
        self.assertEqual(
            normalize_url("https://instagram.com/reel/ABC123?igsh=xyz#frag"),
            "https://www.instagram.com/reel/ABC123/",
        )
        self.assertEqual(normalize_url("m.instagram.com/p/XYZ"), "https://www.instagram.com/p/XYZ/")

    def test_rejects_other_sites_and_home(self):
        self.assertIsNone(normalize_url("https://youtube.com/watch?v=1"))
        self.assertIsNone(normalize_url("https://www.instagram.com/"))
        self.assertIsNone(normalize_url("texto qualquer"))

    def test_parse_sources_dedupes_and_reports_invalid(self):
        text = """
        https://www.instagram.com/reel/AAA/?igsh=1
        https://instagram.com/reel/AAA/, https://www.instagram.com/p/BBB/
        nada-a-ver
        """
        valid, invalid = parse_sources(text)
        self.assertEqual(valid, ["https://www.instagram.com/reel/AAA/", "https://www.instagram.com/p/BBB/"])
        self.assertEqual(invalid, ["nada-a-ver"])


class FilenameTests(unittest.TestCase):
    def test_uses_first_caption_line_without_hashtags_mentions_links(self):
        info = {
            "id": "DcY4rWNNrtb",
            "title": "Video by fulano",
            "description": "\n  Receita de bolo: cenoura #receita @fulano https://x.com/a  \nsegunda linha",
        }
        self.assertEqual(build_filename(info), "Receita de bolo cenoura [DcY4rWNNrtb]")

    def test_truncates_long_titles(self):
        name = build_filename({"id": "X", "description": "a" * 200})
        self.assertEqual(name, "a" * 80 + " [X]")

    def test_falls_back_to_profile_and_date_when_no_caption(self):
        info = {"id": "X", "title": "Video by fulano", "uploader_id": "fulano", "upload_date": "20261027"}
        self.assertEqual(build_filename(info), "fulano_2026-10-27 [X]")
        self.assertEqual(build_filename({"id": "Y", "description": "#so #hashtags"}), "perfil_desconhecido_sem_data [Y]")

    def test_uses_real_title_when_not_generic(self):
        self.assertEqual(build_filename({"id": "Z", "title": "Meu vídeo"}), "Meu vídeo [Z]")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_persists_and_reports_stats(self):
        history = History(self.folder)
        history.add(HistoryEntry(url="u1", ok=True, files=["a.mp4", "b.mp4"], size_bytes=2048))
        history.add(HistoryEntry(url="u2", ok=False, error="falhou"))
        history.add(HistoryEntry(url="u3", ok=True, files=["c.mp4"], size_bytes=1024))

        reloaded = History(self.folder)
        self.assertEqual([e.url for e in reloaded.recent()], ["u3", "u2", "u1"])
        stats = reloaded.stats()
        self.assertEqual((stats.successes, stats.failures, stats.files, stats.total_bytes), (2, 1, 3, 3072))
        self.assertAlmostEqual(stats.success_rate, 2 / 3)
        self.assertEqual(stats.last_success.url, "u3")

    def test_corrupt_file_is_preserved(self):
        (self.folder / HISTORY_FILENAME).write_text("{nao é json", encoding="utf-8")
        history = History(self.folder)
        self.assertEqual(history.recent(), [])
        self.assertTrue((self.folder / "historico_downloads.corrompido.json").exists())

    def test_empty_stats(self):
        self.assertIsNone(History(self.folder).stats().success_rate)


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_rejects_repo_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            Settings(download_dir=tmp, max_workers=3, cookies_browser="firefox").save(path)
            loaded = Settings.load(path)
            self.assertEqual((loaded.download_dir, loaded.max_workers, loaded.cookies_browser), (tmp, 3, "firefox"))

            path.write_text(json.dumps({"download_dir": str(APP_ROOT / "videos")}), encoding="utf-8")
            self.assertNotIn(str(APP_ROOT), Settings.load(path).download_dir)


class FormatSizeTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(format_size(500), "500 B")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(5 * 1024**3), "5.0 GB")


if __name__ == "__main__":
    unittest.main()
