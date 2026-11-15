"""Catálogo de bandas, radios y antenas (data/equipos.json)."""
from __future__ import annotations

import json
from pathlib import Path


class Catalogo:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.datos = json.loads(self.ruta.read_text(encoding="utf-8"))

    @property
    def bandas(self) -> list[dict]:
        return self.datos["bandas"]

    @property
    def antenas(self) -> list[dict]:
        return self.datos["antenas"]

    @property
    def radio(self) -> dict:
        return self.datos["radio"]

    def banda(self, nombre: str) -> dict:
        for b in self.bandas:
            if b["banda"] == nombre:
                return b
        raise KeyError(nombre)

    def antena(self, diametro_m: float) -> dict:
        for a in self.antenas:
            if abs(a["diametro_m"] - diametro_m) < 1e-6:
                return a
        raise KeyError(diametro_m)

    def modulaciones(self, banda: str, ancho_MHz: int) -> list[dict]:
        """Tabla ACM para la banda y el ancho de canal: capacidad, umbral (BER 1e-6) y Ptx."""
        b = self.banda(banda)
        if ancho_MHz not in b["anchos_MHz"]:
            raise ValueError(f"{ancho_MHz} MHz no está canalizado en {banda}")
        tabla = []
        for m in self.radio["modulaciones_56MHz"]:
            fila = dict(m)
            if ancho_MHz == 28:
                fila["capacidad_Mbps"] = round(m["capacidad_Mbps"] * 0.5, 1)
                fila["umbral_dBm"] = m["umbral_dBm"] - 3.0
            fila["ptx_dBm"] = m["ptx_dBm"] + b["ajuste_ptx_dB"]
            tabla.append(fila)
        return tabla

    def modulacion_minima(self, banda: str, ancho_MHz: int, capacidad_Mbps: float) -> dict | None:
        for m in self.modulaciones(banda, ancho_MHz):
            if m["capacidad_Mbps"] >= capacidad_Mbps:
                return m
        return None
