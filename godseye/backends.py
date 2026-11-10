"""Extension seam for trusted, locally installed experiment backends.

Backends are Python code with the permissions of their caller, not a sandbox.
The public web demo does not import plugins or accept executable uploads.
"""
from pathlib import Path
from typing import Any, Dict, Mapping, Protocol, Tuple

import numpy as np

TensorLayout = Mapping[str, Tuple[str, Tuple[int, ...]]]
Weights = Dict[str, np.ndarray]
DATA_DIR = Path(__file__).parent / "data"


class Backend(Protocol):
    id: str
    initial_id: str
    initial_name: str
    layout: TensorLayout

    def initial_weights(self) -> Weights:
        """Return independent float32 arrays matching layout."""
        ...

    def compare(self, base: Weights, candidate: Weights, **settings: Any) -> dict:
        """Return JSON-serializable evidence and actual evaluation counts."""
        ...


class BreakoutBackend:
    id = "minatar-breakout-v1"
    initial_id = "paper"
    initial_name = "Paper · authored network"

    @property
    def layout(self):
        from .core import NAMES
        return NAMES

    def initial_weights(self):
        from .core import load_weights
        return load_weights(DATA_DIR / "breakout/paper.npz", self.layout)

    def compare(self, base, candidate, **settings):
        from .core import compare
        return compare(base, candidate, **settings)
