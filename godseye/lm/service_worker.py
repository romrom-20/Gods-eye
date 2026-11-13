"""Transport-independent local process adapter. No model imports in the control service.

The service owns each inference process directly, bypassing the CLI supervisor.
The inherited flock descriptor fences admission even if the server is killed.
"""
import json
import os
from pathlib import Path
import subprocess

from .local_runtime import FILES, MODEL, REVISION, VERSIONS, WEIGHT_BYTES


class LocalWorker:
    def __init__(self, cache, python):
        self.cache, self.python = Path(cache), Path(python)
        self.source = Path(__file__).resolve().parents[2]

    def readiness(self):
        if not self.cache.is_absolute():
            return 'Set GODSEYE_LM_CACHE to the absolute existing pinned cache directory.'
        if not self.python.is_absolute() or not os.access(self.python, os.X_OK):
            return 'Set GODSEYE_LM_PYTHON to an executable absolute isolated Python interpreter.'
        try:
            source = self.cache / 'source.json'
            if source.is_symlink() or source.stat().st_size > 1000000:
                raise ValueError()
            metadata = json.loads(source.read_text())
            entries = {e['rfilename']: e for e in metadata['siblings']}
            if metadata['sha'] != REVISION or entries['model.safetensors']['size'] != WEIGHT_BYTES:
                raise ValueError()
            for name in FILES:
                path = self.cache / name
                if path.is_symlink() or not path.is_file() or path.stat().st_size != entries[name]['size']:
                    raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            return 'GODSEYE_LM_CACHE needs the existing pinned Qwen cache and source metadata; no downloads are performed.'
        try:
            # Metadata only: never import Torch, load weights, authenticate or use network.
            script = ('import importlib.metadata as m,json; '
                      'print(json.dumps({n:m.version(n).split("+")[0] for n in '
                      + repr(list(VERSIONS)) + '}))')
            result = subprocess.run([str(self.python), '-I', '-c', script],
                                    capture_output=True, timeout=3, check=True)
            if len(result.stdout) > 4096 or json.loads(result.stdout) != VERSIONS:
                raise ValueError()
        except (OSError, ValueError, subprocess.SubprocessError):
            return 'GODSEYE_LM_PYTHON needs the pinned local runtime packages documented in local-lm-service.md.'
        if not (self.source / 'experiments/local_lm_task.py').is_file():
            return 'Run from the documented source checkout; the local task CLI is required.'
        return None

    def launch(self, output, stage, guard_fd):
        # --worker/--verify-selected are leaf processes, NOT the CLI supervisor.
        command = [str(self.python), '-m', 'experiments.local_lm_task', '--execute',
                   '--worker' if stage == 'task' else '--verify-selected',
                   '--cache', str(self.cache), '--output', str(output)]
        # Do not pass provider credentials, Python path injection or HF authentication.
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG') if k in os.environ}
        env.update(OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                   VECLIB_MAXIMUM_THREADS='2', HF_HUB_OFFLINE='1',
                   HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false')
        return subprocess.Popen(command, cwd=self.source, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, pass_fds=(guard_fd,))
