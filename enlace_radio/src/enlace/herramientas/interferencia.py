"""Interferencias: diagrama de radiación de referencia ITU-R F.699 y criterio I/N (ITU-R F.758)."""
from __future__ import annotations

import math

from .propagacion import longitud_onda_m, perdida_espacio_libre_dB


def ganancia_fuera_eje_dBi(Gmax: float, diametro_m: float, f_GHz: float, phi_deg: float) -> float:
    """Diagrama de referencia ITU-R F.699 (1 a 70 GHz)."""
    phi = abs(phi_deg)
    Dl = diametro_m / longitud_onda_m(f_GHz)
    if Dl > 100:
        G1 = 2 + 15 * math.log10(Dl)
        phim = 20 / Dl * math.sqrt(max(Gmax - G1, 0))
        phir = 15.85 * Dl ** -0.6
        if phi < phim:
            return Gmax - 2.5e-3 * (Dl * phi) ** 2
        if phi < max(phir, phim):
            return G1
        if phi < 48:
            return 32 - 25 * math.log10(phi)
        return -10.0
    G1 = 2 + 15 * math.log10(Dl)
    phim = 20 / Dl * math.sqrt(max(Gmax - G1, 0))
    if phi < phim:
        return Gmax - 2.5e-3 * (Dl * phi) ** 2
    if phi < 100 / Dl:
        return G1
    if phi < 48:
        return 52 - 10 * math.log10(Dl) - 25 * math.log10(phi)
    return 10 - 10 * math.log10(Dl)


def ruido_termico_dBm(ancho_MHz: float, nf_dB: float) -> float:
    return -174.0 + 10 * math.log10(ancho_MHz * 1e6) + nf_dB


def evaluar_escenario(esc: dict, f_GHz: float, Gmax_rx: float, diametro_m: float, perdidas_rx_dB: float,
                      ancho_MHz: float, nf_dB: float, prx_nominal_dBm: float, snr_req_dB: float,
                      eficiencia: float = 0.58) -> dict:
    """Interferencia de un transmisor cocanal: ambos diagramas fuera del eje según ITU-R F.699."""
    from .propagacion import ganancia_parabolica_dBi

    Gi_max = ganancia_parabolica_dBi(esc["antena_interferente_m"], f_GHz, eficiencia)
    g_tx = ganancia_fuera_eje_dBi(Gi_max, esc["antena_interferente_m"], f_GHz, esc["angulo_fuera_eje_interferente_deg"])
    g_rx = ganancia_fuera_eje_dBi(Gmax_rx, diametro_m, f_GHz, esc["angulo_fuera_eje_victima_deg"])
    pire = esc["ptx_interferente_dBm"] + g_tx
    I = (pire - perdida_espacio_libre_dB(esc["distancia_km"], f_GHz) + g_rx - perdidas_rx_dB
         - esc.get("discriminacion_polarizacion_dB", 0.0))
    N = ruido_termico_dBm(ancho_MHz, nf_dB)
    i_n = I - N
    td = 10 * math.log10(1 + 10 ** (i_n / 10))
    c_i = prx_nominal_dBm - I
    return {
        "nombre": esc["nombre"], "distancia_km": esc["distancia_km"],
        "angulo_victima_deg": esc["angulo_fuera_eje_victima_deg"], "G_tx_fuera_eje_dBi": g_tx,
        "G_fuera_eje_dBi": g_rx, "pire_hacia_victima_dBm": pire, "I_dBm": I, "N_dBm": N, "I_N_dB": i_n,
        "degradacion_umbral_dB": td, "C_I_dB": c_i, "C_I_requerida_dB": snr_req_dB + 10.0,
        "cumple": i_n <= -6.0,  # criterio de largo plazo de ITU-R F.758 (degradación <= 1 dB)
    }
