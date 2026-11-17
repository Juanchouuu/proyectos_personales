"""Registro de actividad: un archivo JSON Lines con cada turno de conversación."""

import json
import threading
from datetime import datetime
from pathlib import Path


class Registro:
    def __init__(self, archivo: Path):
        self.archivo = archivo
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()

    def escribir(self, entrada: dict) -> None:
        entrada = {"fecha": datetime.now().isoformat(timespec="seconds"), **entrada}
        linea = json.dumps(entrada, ensure_ascii=False)
        with self._candado, self.archivo.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")

    def ultimos(self, n: int = 20) -> list[dict]:
        if not self.archivo.exists():
            return []
        with self._candado:
            lineas = self.archivo.read_text(encoding="utf-8").splitlines()[-n:]
        resultado = []
        for linea in lineas:
            try:
                resultado.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
        return resultado
