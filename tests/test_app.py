import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

import app


class AppTests(unittest.TestCase):
    def test_background_job_creates_copy_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            image_path = source / "image.png"
            Image.new("RGB", (40, 30), "blue").save(image_path)

            client = app.app.test_client()
            response = client.post(
                "/start", json={"folders": [str(source)], "quality": 82}
            )
            self.assertEqual(response.status_code, 200)
            job_id = response.get_json()["job_id"]

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                job = client.get(f"/status/{job_id}").get_json()
                if job["status"] != "running":
                    break
                time.sleep(0.1)

            self.assertEqual(job["status"], "complete", job)
            report = job["reports"][0]
            self.assertEqual(report["images"], 1)
            self.assertTrue((Path(report["output"]) / "image.png").exists())
            self.assertTrue(image_path.exists())


if __name__ == "__main__":
    unittest.main()
