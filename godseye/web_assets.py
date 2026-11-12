"""Keep served and exported HTML paired with its actual asset contents."""
import hashlib
from pathlib import Path


def page_html(name, static=None):
    static = Path(static) if static is not None else Path(__file__).parent / 'static'
    html = (static / name).read_text()
    for asset in ('style.css', 'app.js', 'landing.css', 'landing.js'):
        revision = hashlib.sha256((static / asset).read_bytes()).hexdigest()[:16]
        html = html.replace('"' + asset + '"', '"' + asset + '?v=' + revision + '"')
    return html
