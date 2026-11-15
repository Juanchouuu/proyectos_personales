#!/usr/bin/env python3
"""Atajo: ejecuta el sistema multiagente y regenera salida/informe_enlace_radio.pdf.

Uso:  python generar_informe.py [--motor reglas|claude|auto] [--sin-red] [-v]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from enlace.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
