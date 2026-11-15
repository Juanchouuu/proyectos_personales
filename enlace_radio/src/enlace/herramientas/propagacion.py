"""Propagación en visibilidad directa: pérdidas, Fresnel, curvatura y alturas de antena.

Unidades: distancias en km, frecuencias en GHz, alturas en m, potencias en dB/dBm.
"""
from __future__ import annotations

import math

import numpy as np

C = 299_792_458.0  # m/s


def longitud_onda_m(f_GHz: float) -> float:
    return C / (f_GHz * 1e9)


def perdida_espacio_libre_dB(d_km: float, f_GHz: float) -> float:
    """FSPL = 92.45 + 20 log10(f[GHz]) + 20 log10(d[km])  (ITU-R P.525)."""
    return 92.45 + 20 * math.log10(f_GHz) + 20 * math.log10(d_km)


def radio_fresnel_m(d1_km, d2_km, f_GHz: float, n: int = 1):
    """r_n = 17.32 * sqrt(n d1 d2 / (f d))  (ITU-R P.530 / P.526)."""
    d1 = np.asarray(d1_km, dtype=float)
    d2 = np.asarray(d2_km, dtype=float)
    return 17.32 * np.sqrt(n * d1 * d2 / (f_GHz * (d1 + d2)))


def abultamiento_tierra_m(d1_km, d2_km, k: float):
    """Altura equivalente de la curvatura terrestre: h = d1 d2 / (12.74 k)."""
    return np.asarray(d1_km, dtype=float) * np.asarray(d2_km, dtype=float) / (12.74 * k)


def ganancia_parabolica_dBi(diametro_m: float, f_GHz: float, eficiencia: float = 0.58) -> float:
    lam = longitud_onda_m(f_GHz)
    return 10 * math.log10(eficiencia * (math.pi * diametro_m / lam) ** 2)


def ancho_haz_deg(diametro_m: float, f_GHz: float) -> float:
    """Ancho de haz a -3 dB aproximado: 70 lambda / D."""
    return 70.0 * longitud_onda_m(f_GHz) / diametro_m


def atenuacion_gases_dB_km(f_GHz: float, rho_g_m3: float = 7.5) -> tuple[float, float]:
    """Atenuación específica de oxígeno y vapor de agua (dB/km).

    Aproximación simplificada (ITU-R P.676, Anexo 2, versión de baja resolución) válida para f < 57 GHz,
    a nivel del mar y 15 °C. Devuelve (gamma_o, gamma_w).
    """
    f = f_GHz
    go = (7.2 / (f ** 2 + 0.34) + 0.62 / ((54 - f) ** 1.16 + 0.83)) * f ** 2 * 1e-3
    gw = (0.050 + 0.0021 * rho_g_m3 + 3.6 / ((f - 22.2) ** 2 + 8.5) + 10.6 / ((f - 183.3) ** 2 + 9.0)
          + 8.9 / ((f - 325.4) ** 2 + 26.3)) * f ** 2 * rho_g_m3 * 1e-4
    return go, gw


def factor_presion_altitud(h_m: float) -> float:
    """Corrección aproximada de la atenuación por oxígeno con la altitud (presión ~ exp(-h/7.7 km))."""
    return math.exp(-h_m / 7700.0)


def analizar_despeje(d_km, terreno_m, clutter_m, hA_m: float, hB_m: float, f_GHz: float, k: float) -> dict:
    """Despeje sobre el perfil para alturas de antena (sobre el suelo) hA y hB.

    Devuelve la línea de vista, el radio de Fresnel, el terreno efectivo (con curvatura y clutter)
    y el despeje normalizado h/F1 en cada punto intermedio.
    """
    d = np.asarray(d_km, dtype=float)
    t = np.asarray(terreno_m, dtype=float)
    cl = np.asarray(clutter_m, dtype=float)
    D = d[-1]
    zA = t[0] + hA_m
    zB = t[-1] + hB_m
    los = zA + (zB - zA) * d / D
    d1, d2 = d, D - d
    bulge = abultamiento_tierra_m(d1, d2, k)
    obst = t + cl + bulge
    f1 = radio_fresnel_m(d1, d2, f_GHz)
    despeje = los - obst
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(f1 > 0, despeje / f1, np.inf)
    interior = slice(1, -1)
    i_min = int(np.argmin(rel[interior])) + 1
    return {
        "los_m": los, "f1_m": f1, "abultamiento_m": bulge, "obstaculo_m": obst,
        "despeje_m": despeje, "despeje_rel": rel,
        "despeje_rel_min": float(rel[i_min]), "d_critico_km": float(d[i_min]),
        "despeje_min_m": float(despeje[i_min]), "f1_critico_m": float(f1[i_min]),
    }


def alturas_minimas(d_km, terreno_m, clutter_m, f_GHz: float, criterios: list[tuple[float, float]],
                    hA_min: float, hA_max: float, hB_min: float, hB_max: float, paso: float = 1.0) -> dict | None:
    """Busca el par (hA, hB) de menor suma (y luego más equilibrado) que cumple todos los criterios.

    `criterios` es una lista de (k, fracción de F1 exigida).
    """
    mejor = None
    for hA in np.arange(hA_min, hA_max + 1e-9, paso):
        for hB in np.arange(hB_min, hB_max + 1e-9, paso):
            if mejor is not None and hA + hB > mejor[0] + 1e-9:
                break
            ok = all(analizar_despeje(d_km, terreno_m, clutter_m, hA, hB, f_GHz, k)["despeje_rel_min"] >= frac
                     for k, frac in criterios)
            if ok:
                clave = (hA + hB, abs(hA - hB))
                if mejor is None or clave < mejor:
                    mejor = (hA + hB, abs(hA - hB), float(hA), float(hB))
                break
    if mejor is None:
        return None
    return {"hA_m": mejor[2], "hB_m": mejor[3]}
