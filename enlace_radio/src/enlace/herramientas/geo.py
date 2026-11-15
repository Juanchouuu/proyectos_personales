"""Geodesia básica sobre esfera (radio medio terrestre)."""
from __future__ import annotations

import math

R_TIERRA_KM = 6371.0088  # radio medio IUGG


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia de círculo máximo (haversine), km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_TIERRA_KM * math.asin(math.sqrt(a))


def azimut_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Azimut inicial de 1 hacia 2, grados desde el norte verdadero (0-360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def punto_intermedio(lat1: float, lon1: float, lat2: float, lon2: float, frac: float) -> tuple[float, float]:
    """Punto a la fracción `frac` del círculo máximo entre 1 y 2."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = distancia_km(lat1, lon1, lat2, lon2) / R_TIERRA_KM
    if d == 0:
        return lat1, lon1
    a = math.sin((1 - frac) * d) / math.sin(d)
    b = math.sin(frac * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def destino(lat: float, lon: float, azimut: float, dist_km: float) -> tuple[float, float]:
    """Punto a `dist_km` desde (lat, lon) con rumbo `azimut`."""
    p1, l1 = math.radians(lat), math.radians(lon)
    b = math.radians(azimut)
    dr = dist_km / R_TIERRA_KM
    p2 = math.asin(math.sin(p1) * math.cos(dr) + math.cos(p1) * math.sin(dr) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(dr) * math.cos(p1), math.cos(dr) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def formato_dms(valor: float, es_lat: bool) -> str:
    hemi = ("N" if valor >= 0 else "S") if es_lat else ("E" if valor >= 0 else "W")
    v = abs(valor)
    g = int(v)
    m = int((v - g) * 60)
    s = (v - g - m / 60) * 3600
    return f"{g}°{m:02d}'{s:04.1f}\" {hemi}"
