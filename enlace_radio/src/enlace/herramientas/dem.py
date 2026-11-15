"""Acceso al modelo digital de elevación SRTM 1" (teselas Skadi .hgt).

Las teselas se descargan del conjunto abierto *Terrain Tiles* de AWS y se guardan
en ``data/dem``. Si no hay red, se usa el perfil ya extraído en ``data/perfil_terreno.csv``.
"""
from __future__ import annotations

import csv
import gzip
import math
from pathlib import Path

import numpy as np

from . import geo

URL = "https://elevation-tiles-prod.s3.amazonaws.com/skadi/{lat_dir}/{nombre}.hgt.gz"
N = 3601  # muestras por lado (1 arc-segundo)


def nombre_tesela(lat: float, lon: float) -> tuple[str, str]:
    la, lo = math.floor(lat), math.floor(lon)
    lat_dir = f"{'N' if la >= 0 else 'S'}{abs(la):02d}"
    return lat_dir, f"{lat_dir}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


class DEM:
    def __init__(self, carpeta: Path, url: str = URL, descargar: bool = True):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.url = url
        self.descargar = descargar
        self._teselas: dict[str, np.ndarray] = {}
        self.teselas_usadas: list[str] = []

    def _tesela(self, lat: float, lon: float) -> np.ndarray:
        lat_dir, nombre = nombre_tesela(lat, lon)
        if nombre in self._teselas:
            return self._teselas[nombre]
        ruta = self.carpeta / f"{nombre}.hgt.gz"
        if not ruta.exists():
            if not self.descargar:
                raise FileNotFoundError(ruta)
            import requests

            r = requests.get(self.url.format(lat_dir=lat_dir, nombre=nombre), timeout=120)
            r.raise_for_status()
            ruta.write_bytes(r.content)
        datos = np.frombuffer(gzip.decompress(ruta.read_bytes()), dtype=">i2").reshape(N, N).astype(float)
        datos[datos < -1000] = np.nan  # huecos SRTM
        self._teselas[nombre] = datos
        self.teselas_usadas.append(nombre)
        return datos

    def elevacion(self, lat: float, lon: float) -> float:
        """Elevación (m s. n. m., EGM96) con interpolación bilineal."""
        a = self._tesela(lat, lon)
        la, lo = math.floor(lat), math.floor(lon)
        f = (la + 1 - lat) * (N - 1)
        c = (lon - lo) * (N - 1)
        f0, c0 = int(f), int(c)
        f1, c1 = min(f0 + 1, N - 1), min(c0 + 1, N - 1)
        df, dc = f - f0, c - c0
        v = (a[f0, c0] * (1 - df) * (1 - dc) + a[f0, c1] * (1 - df) * dc
             + a[f1, c0] * df * (1 - dc) + a[f1, c1] * df * dc)
        return float(v)

    def perfil(self, lat1, lon1, lat2, lon2, paso_m: float = 30.0) -> dict:
        d = geo.distancia_km(lat1, lon1, lat2, lon2)
        n = max(2, int(round(d * 1000 / paso_m)))
        dist, lats, lons, elev = [], [], [], []
        for i in range(n + 1):
            fr = i / n
            la, lo = geo.punto_intermedio(lat1, lon1, lat2, lon2, fr)
            dist.append(d * fr)
            lats.append(la)
            lons.append(lo)
            elev.append(self.elevacion(la, lo))
        return {"d_km": np.array(dist), "lat": np.array(lats), "lon": np.array(lons), "h_m": np.array(elev)}

    def rejilla(self, lat_min, lat_max, lon_min, lon_max, n: int = 300) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        lats = np.linspace(lat_max, lat_min, n)
        lons = np.linspace(lon_min, lon_max, n)
        z = np.array([[self.elevacion(la, lo) for lo in lons] for la in lats])
        return lats, lons, z


def guardar_perfil_csv(perfil: dict, ruta: Path) -> None:
    with open(ruta, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["d_km", "lat", "lon", "h_m"])
        for i in range(len(perfil["d_km"])):
            w.writerow([f"{perfil['d_km'][i]:.5f}", f"{perfil['lat'][i]:.6f}", f"{perfil['lon'][i]:.6f}", f"{perfil['h_m'][i]:.2f}"])


def leer_perfil_csv(ruta: Path) -> dict:
    cols = {"d_km": [], "lat": [], "lon": [], "h_m": []}
    with open(ruta) as f:
        for fila in csv.DictReader(f):
            for k in cols:
                cols[k].append(float(fila[k]))
    return {k: np.array(v) for k, v in cols.items()}
