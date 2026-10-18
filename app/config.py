from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent

@dataclass
class Settings:
    data_dir: Path
    testing: bool = False
    worker_interval: float = 0.5
    send_interval_override: float | None = None

    @classmethod
    def from_env(cls):
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
        return cls(Path(os.environ.get('HMR_DATA_DIR', str(base / 'HomeworkReminder'))))
