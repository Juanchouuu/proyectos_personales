"""Modelos de recomendaciones ITU-R usados en el cálculo de disponibilidad.

* ITU-R P.838-3: coeficientes k y alfa de la atenuación específica por lluvia.
* ITU-R P.530-18 §2.4.1: atenuación por lluvia excedida el 0,01 % y escalado a otros porcentajes.
* ITU-R P.530-18 §2.3.1: probabilidad de desvanecimiento por multitrayecto (método rápido).
"""
from __future__ import annotations

import math

# ---- ITU-R P.838-3, Tablas 1 a 4 -------------------------------------------------------------
_KH = ([-5.33980, -0.35351, -0.23789, -0.94158], [-0.10008, 1.26970, 0.86036, 0.64552],
       [1.13098, 0.45400, 0.15354, 0.16817], -0.18961, 0.71147)
_KV = ([-3.80595, -3.44965, -0.39902, 0.50167], [0.56934, -0.22911, 0.73042, 1.07319],
       [0.81061, 0.51059, 0.11899, 0.27195], -0.16398, 0.63297)
_AH = ([-0.14318, 0.29591, 0.32177, -5.37610, 16.1721], [1.82442, 0.77564, 0.63773, -0.96230, -3.29980],
       [-0.55187, 0.19822, 0.13164, 1.47828, 3.43990], 0.67849, -1.95537)
_AV = ([-0.07771, 0.56727, -0.20238, -48.2991, 48.5833], [2.33840, 0.95545, 1.14520, 0.791669, 0.791459],
       [-0.76284, 0.54039, 0.26809, 0.116226, 0.116479], -0.053739, 0.83433)


def _suma(coef, lf):
    a, b, c, m, cc = coef
    return sum(aj * math.exp(-(((lf - bj) / cj) ** 2)) for aj, bj, cj in zip(a, b, c)) + m * lf + cc


def coeficientes_lluvia(f_GHz: float, polarizacion: str = "V", elevacion_deg: float = 0.0) -> tuple[float, float]:
    """Devuelve (k, alfa) de ITU-R P.838-3 para polarización 'H' o 'V' (enlace casi horizontal)."""
    lf = math.log10(f_GHz)
    kH = 10 ** _suma(_KH, lf)
    kV = 10 ** _suma(_KV, lf)
    aH = _suma(_AH, lf)
    aV = _suma(_AV, lf)
    tau = 0.0 if polarizacion.upper() == "H" else 90.0
    c = math.cos(math.radians(elevacion_deg)) ** 2 * math.cos(math.radians(2 * tau))
    k = (kH + kV + (kH - kV) * c) / 2
    alfa = (kH * aH + kV * aV + (kH * aH - kV * aV) * c) / (2 * k)
    return k, alfa


def atenuacion_especifica_lluvia(f_GHz: float, R_mm_h: float, polarizacion: str = "V") -> float:
    k, a = coeficientes_lluvia(f_GHz, polarizacion)
    return k * R_mm_h ** a


def factor_distancia_r(d_km: float, f_GHz: float, R: float, alfa: float) -> float:
    """Factor de reducción de distancia de ITU-R P.530-18, ec. (37). Limitado a 2,5."""
    den = 0.477 * d_km ** 0.633 * R ** (0.073 * alfa) * f_GHz ** 0.123 - 10.579 * (1 - math.exp(-0.024 * d_km))
    r = 1 / den if den > 0 else 2.5
    return min(r, 2.5)


def atenuacion_lluvia_001(d_km: float, f_GHz: float, R001: float, polarizacion: str = "V") -> dict:
    k, a = coeficientes_lluvia(f_GHz, polarizacion)
    gamma = k * R001 ** a
    r = factor_distancia_r(d_km, f_GHz, R001, a)
    return {"k": k, "alfa": a, "gamma_dB_km": gamma, "r": r, "d_eff_km": r * d_km, "A001_dB": gamma * r * d_km}


def _coef_escalado(f_GHz: float) -> tuple[float, float, float]:
    C0 = 0.12 + 0.4 * math.log10((f_GHz / 10) ** 0.8) if f_GHz >= 10 else 0.12
    C1 = (0.07 ** C0) * (0.12 ** (1 - C0))
    C2 = 0.855 * C0 + 0.546 * (1 - C0)
    C3 = 0.139 * C0 + 0.043 * (1 - C0)
    return C1, C2, C3


def atenuacion_lluvia_p(A001: float, p_pct: float, f_GHz: float) -> float:
    """A_p = A_0.01 * C1 p^-(C2 + C3 log10 p), válido para 0,001 % <= p <= 1 % (latitud < 30°)."""
    C1, C2, C3 = _coef_escalado(f_GHz)
    return A001 * C1 * p_pct ** (-(C2 + C3 * math.log10(p_pct)))


def porcentaje_excedido_lluvia(A001: float, margen_dB: float, f_GHz: float) -> float:
    """Porcentaje del año en que la atenuación por lluvia supera `margen_dB` (inversión numérica).

    Se acota a [1e-4, 1] %. Por debajo de 1e-3 % el modelo se extrapola (se informa como tal).
    """
    lo, hi = math.log10(1e-4), math.log10(1.0)
    if atenuacion_lluvia_p(A001, 10 ** hi, f_GHz) >= margen_dB:
        return 1.0
    if atenuacion_lluvia_p(A001, 10 ** lo, f_GHz) <= margen_dB:
        return 1e-4
    for _ in range(80):
        mid = (lo + hi) / 2
        if atenuacion_lluvia_p(A001, 10 ** mid, f_GHz) > margen_dB:
            lo = mid
        else:
            hi = mid
    return 10 ** ((lo + hi) / 2)


def multitrayecto(d_km: float, f_GHz: float, dN1: float, hA_msnm: float, hB_msnm: float, margen_dB: float) -> dict:
    """Método rápido de ITU-R P.530-18 §2.3.1 (ecs. 9 y 10) para el mes más desfavorable.

    hA_msnm y hB_msnm son las alturas de las antenas sobre el nivel del mar.
    """
    K = 10 ** (-4.6 - 0.0027 * dN1)
    eps_p = abs(hA_msnm - hB_msnm) / d_km  # mrad
    hL = min(hA_msnm, hB_msnm)
    p0 = K * d_km ** 3.1 * (1 + eps_p) ** -1.29 * f_GHz ** 0.8 * 10 ** (-0.00089 * hL)
    pw = p0 * 10 ** (-margen_dB / 10)
    return {"K": K, "eps_p_mrad": eps_p, "hL_m": hL, "p0_pct": p0, "pw_pct": min(pw, 100.0)}
