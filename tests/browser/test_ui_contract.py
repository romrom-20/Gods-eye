"""Ensure the bundled browser validator matches the published Python contract."""
import json
from pathlib import Path
import unittest

from godseye.experiment_spec import MESSAGES, SCHEMAS, _SAFE_PATHS, retry_guidance


class BrowserContract(unittest.TestCase):
    def test_bundled_contract_matches_service(self):
        source = (Path(__file__).resolve().parents[2] / 'godseye/static/app.js').read_text()
        value = source.split('const experimentContract = ', 1)[1].split(';\n', 1)[0]
        self.assertEqual(json.loads(value), dict(
            schemas=SCHEMAS, messages=MESSAGES, paths=sorted(_SAFE_PATHS),
            retries={code: retry_guidance(code) for code in MESSAGES}))


if __name__ == '__main__':
    unittest.main()
