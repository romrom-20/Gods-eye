"""Landing evidence must remain identical to the bundled public recording."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit

from godseye.export import export_demo

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.ids = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag == 'a':
            self.links.append(attrs['href'])


class LandingTest(unittest.TestCase):
    def test_gameplay_and_statistics_are_bundled_evidence(self):
        js = (ROOT / 'godseye/static/landing.js').read_text()
        frames = json.loads(re.search(r'const recordedFrames = (\[.*?\]);', js).group(1))
        run = json.loads((ROOT / 'godseye/data/demo/run-3ed8cc40701c4335.json').read_text())
        self.assertEqual(len(frames), 14)
        for frame in frames:
            self.assertEqual(frame['base'], run['base']['trace'][frame['step']]['cells'])
            self.assertEqual(frame['candidate'], run['candidate']['trace'][min(frame['step'], 5)]['cells'])
        html = (ROOT / 'godseye/static/landing.html').read_text()
        for number in [str(run['base']['mean']), str(run['paired_mean_delta']).replace('-', '−'),
                       f"{run['paired_se']:.3f}"]:
            self.assertIn(number, html)
        self.assertEqual(sum(e['truncated'] for e in run['base']['episodes']), 7)
        # Initial no-JS evidence has exactly the source frame's cells and coordinates.
        for side in ('base', 'candidate'):
            body = re.search(fr'id="board-{side}".*?>(.*?)</svg>', html).group(1)
            rects = re.findall(r'<rect x="(\d+)" y="(\d+)"', body)
            cells = run[side]['trace'][5]['cells']
            expected = [(str(col * 10 + 1), str(row * 10 + 1))
                        for channel in [3, 2, 0, 1] for row, col in cells[channel]]
            self.assertEqual(rects, expected)

    def test_export_links_and_no_network_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            output = export_demo(Path(directory) / 'Gods-eye')
            html = (output / 'index.html').read_text()
            parsed = Links(html)
            for link in parsed.links:
                url = urlsplit(link)
                if url.scheme:
                    self.assertEqual(url.scheme, 'https')
                    if '/blob/main/' in url.path:
                        self.assertTrue((ROOT / url.path.split('/blob/main/', 1)[1]).is_file(), link)
                    continue
                self.assertFalse(link.startswith('/'), link)
                file = output / (url.path or 'index.html')
                if file.is_dir():
                    file /= 'index.html'
                self.assertTrue(file.is_file(), link)
                if url.fragment:
                    if url.path == 'lab.html':
                        self.assertIn(f'data-view="{url.fragment}"', file.read_text(), link)
                    else:
                        self.assertIn(url.fragment, Links(file.read_text()).ids, link)
            js = (output / 'landing.js').read_text()
            self.assertNotRegex(js, r'\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(')
            self.assertNotRegex(html, r'(?:src|href)="https?://[^\"]+\.(?:css|js|woff)(?:\?[^\"]*)?\"')
            self.assertIn('Currently compatible with Breakout only.', html)
            self.assertIn('Recorded example', html)
            self.assertIn('harmful edit', html)
            self.assertIn('prefers-reduced-motion', (output / 'landing.css').read_text())


if __name__ == '__main__':
    unittest.main()
