"""Crash-safe publication of individual local artifacts."""
import json
import os
from pathlib import Path
import tempfile


def atomic_write(path, data):
    """Readers see the old complete file or the new complete file, never a prefix."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, allow_nan=False, indent=2).encode())
