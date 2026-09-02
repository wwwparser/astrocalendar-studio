"""Запуск: python -m astrocal_studio"""
from __future__ import annotations

import sys
from pathlib import Path

# Запуск из исходников без установки пакета
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from astrocal_studio.app import main      # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
