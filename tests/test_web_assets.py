import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from godseye.export import export_demo
from godseye.web_assets import page_html


class AssetRevisionTests(unittest.TestCase):
    def test_html_and_export_reference_the_exact_asset_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = export_demo(directory)
            for name in ('index.html', 'lab.html'):
                html = (root / name).read_text()
                matches = re.findall(r'(?:src|href)="([^"?]+\.(?:css|js))\?v=([a-f0-9]+)"', html)
                self.assertEqual(len(matches), 2)
                for asset, revision in matches:
                    self.assertEqual(revision, hashlib.sha256((root / asset).read_bytes()).hexdigest()[:16])
            self.assertIn('data-static-demo="true"', (root / 'lab.html').read_text())

    def test_changing_an_asset_changes_its_url_without_a_manual_version_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for asset in ('app.js', 'style.css', 'landing.css', 'landing.js'):
                (root / asset).write_text('old')
            (root / 'index.html').write_text('<script src="app.js"></script>')
            old = page_html('index.html', root)
            (root / 'app.js').write_text('new')
            self.assertNotEqual(old, page_html('index.html', root))
