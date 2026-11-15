"""Subagente revisor: recalcula de forma independiente y comprueba la coherencia del diseño elegido.

Usa fórmulas alternativas (no las mismas funciones que los demás agentes) para detectar errores
de unidades, de transcripción o de lógica antes de que se genere el informe.
"""
from __future__ import annotations

import math

import numpy as np

from ..herramientas import itur
from .base import Agente, Pizarra, Resultado

# Valores publicados en las tablas de ITU-R P.838-3 (referencia de control)
TABLA_P838 = {10.0: (0.01217, 1.2571, 0.01129, 1.2156), 20.0: (0.09164, 1.0568, 0.09611, 0.9847),
              8.0: (0.004115, 1.3905, 0.003450, 1.3797)}


class AgenteRevisor(Agente):
    nombre = "revisor"
    rol = ("Revisión técnica independiente: recalcula pérdidas, Fresnel, distancia, coeficientes ITU-R y el "
           "presupuesto con fórmulas alternativas, y valida la coherencia de las decisiones y los requisitos.")
    herramientas = ["fórmulas independientes (Friis, ley de cosenos esférica, λ)", "tablas ITU-R P.838-3"]

    def ejecutar(self, pz: Pizarra, diseno: dict, evaluados: list[dict] | None = None, **_) -> Resultado:
        n0 = len(pz.verificaciones)
        v = lambda nombre, ok, det, critica=True: pz.verificar(self.nombre, nombre, ok, det, critica)  # noqa: E731
        req = self.ctx.config["requisitos"]
        A, B = pz.leer("sitio_A"), pz.leer("sitio_B")
        d = pz.leer("distancia_km")
        f = diseno["f_GHz"]
        pres = diseno["presupuesto"]

        # 1. distancia por la ley de cosenos esférica
        p1, p2 = math.radians(A["lat"]), math.radians(B["lat"])
        dl = math.radians(B["lon"] - A["lon"])
        d2 = 6371.0088 * math.acos(min(1.0, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)))
        v("Distancia (ley de cosenos)", abs(d2 - d) < 0.01, f"{d2:.3f} km frente a {d:.3f} km")

        # 2. pérdida en espacio libre con Friis (4πd/λ)^2
        lam = 299_792_458.0 / (f * 1e9)
        fspl2 = 20 * math.log10(4 * math.pi * d * 1000 / lam)
        v("FSPL (Friis)", abs(fspl2 - pres["FSPL_dB"]) < 0.05, f"{fspl2:.2f} dB frente a {pres['FSPL_dB']:.2f} dB")

        # 3. ganancia de antena desde área efectiva
        ef = self.ctx.catalogo.antena(diseno["antena_m"])["eficiencia"]
        g2 = 10 * math.log10(4 * math.pi * ef * math.pi * (diseno["antena_m"] / 2) ** 2 / lam ** 2)
        v("Ganancia de antena (área efectiva)", abs(g2 - pres["G_dBi"]) < 0.05, f"{g2:.2f} dBi frente a {pres['G_dBi']:.2f} dBi")
        v("Ganancia en rango de catálogo", 25 < pres["G_dBi"] < 50, f"{pres['G_dBi']:.1f} dBi")

        # 4. suma del presupuesto
        ref = pres["ref"]
        prx2 = (ref["ptx_dBm"] - pres["Lt_dB"] + 2 * pres["G_dBi"] - pres["FSPL_dB"] - pres["A_gases_dB"]
                - pres["Lr_dB"] - pres["Lvarias_dB"])
        v("Suma del presupuesto de potencia", abs(prx2 - ref["prx_dBm"]) < 1e-6, f"Prx = {prx2:.2f} dBm")
        v("Receptor no saturado", ref["prx_dBm"] <= self.ctx.catalogo.radio["prx_max_dBm"],
          f"Prx = {ref['prx_dBm']:.1f} dBm <= {self.ctx.catalogo.radio['prx_max_dBm']} dBm")
        v("Atenuación por gases plausible", 0 < pres["A_gases_dB"] < 0.1 * d + 0.5, f"{pres['A_gases_dB']:.2f} dB")

        # 5. Fresnel con λ: r = sqrt(λ d1 d2 / d) en el punto crítico
        det = diseno["alturas"]["detalle"]["k_mediano"]
        d1 = det["d_critico_km"] * 1000
        r2 = math.sqrt(lam * d1 * (d * 1000 - d1) / (d * 1000))
        v("Radio de Fresnel (λ)", abs(r2 - det["f1_critico_m"]) / r2 < 0.01, f"{r2:.2f} m frente a {det['f1_critico_m']:.2f} m")

        # 6. despeje recalculado de forma vectorial independiente
        perf = pz.leer("perfil")
        dd, h, cl = perf["d_km"], perf["h_m"], perf["clutter_m"]
        zA, zB = h[0] + diseno["alturas"]["hA_m"], h[-1] + diseno["alturas"]["hB_m"]
        for k, frac in diseno["alturas"]["criterios"]:
            x = dd * 1000
            D = x[-1]
            curv = x * (D - x) / (2 * k * 6_371_008.8)  # m
            los = zA + (zB - zA) * x / D
            fr = np.sqrt(lam * x * (D - x) / D)
            with np.errstate(divide="ignore", invalid="ignore"):
                rel = (los - (h + cl + curv)) / fr
            mn = float(np.nanmin(rel[1:-1]))
            v(f"Despeje k={k:.2f} >= {frac:.1f} F1", mn >= frac - 0.01, f"h/F1 mínimo = {mn:.2f}")

        # 7. coeficientes P.838-3 frente a la tabla publicada
        for fr_, (kh, ah, kv, av) in TABLA_P838.items():
            kH, aH = itur.coeficientes_lluvia(fr_, "H")
            kV, aV = itur.coeficientes_lluvia(fr_, "V")
            ok = (abs(kH - kh) / kh < 0.01 and abs(kV - kv) / kv < 0.01 and abs(aH - ah) < 0.005 and abs(aV - av) < 0.005)
            v(f"P.838-3 a {fr_:.0f} GHz", ok, f"kH={kH:.5f}, αH={aH:.4f}, kV={kV:.5f}, αV={aV:.4f}")

        # 8. coherencia de la inversión lluvia-margen
        disp = diseno["disponibilidad"]
        pl = disp["ref"]["p_lluvia_pct"]
        if 1e-4 < pl < 1:
            a_p = itur.atenuacion_lluvia_p(disp["lluvia"]["A001_dB"], pl, f)
            v("Inversión A(p) = margen", abs(a_p - disp["ref"]["margen_efectivo_dB"]) < 0.05,
              f"A({pl:.2e} %) = {a_p:.2f} dB, margen = {disp['ref']['margen_efectivo_dB']:.2f} dB")
        v("Lluvia monótona en p", itur.atenuacion_lluvia_p(10, 0.001, f) > itur.atenuacion_lluvia_p(10, 0.01, f)
          > itur.atenuacion_lluvia_p(10, 0.1, f), "A(0,001 %) > A(0,01 %) > A(0,1 %)")
        v("Validez del modelo de lluvia", not disp["extrapolado"],
          "p dentro del rango 0,001-1 % de P.530" if not disp["extrapolado"]
          else "p < 0,001 %: extrapolación (resultado holgado, no crítico)", critica=False)

        # 9. requisitos
        v("Capacidad >= requisito", ref["capacidad_Mbps"] >= req["capacidad_minima_mbps"],
          f"{ref['capacidad_Mbps']:.0f} Mbps con {ref['mod']}")
        v("Disponibilidad >= objetivo", disp["ref"]["disponibilidad_pct"] >= req["disponibilidad_objetivo_pct"],
          f"{disp['ref']['disponibilidad_pct']:.5f} % (objetivo {req['disponibilidad_objetivo_pct']} %)")
        v("Interferencia aceptable", diseno["interferencia"]["cumple"],
          f"degradación máx. {diseno['interferencia']['degradacion_max_dB']:.2f} dB")
        cfgA, cfgB = self.ctx.config["sitios"]["A"], self.ctx.config["sitios"]["B"]
        v("Alturas dentro de los límites de las estructuras",
          diseno["alturas"]["hA_m"] <= cfgA["altura_max_mastil_m"] and diseno["alturas"]["hB_m"] <= cfgB["altura_max_mastil_m"],
          f"hA = {diseno['alturas']['hA_m']:.0f} m, hB = {diseno['alturas']['hB_m']:.0f} m")
        v("Banda licenciada", self.ctx.catalogo.banda(diseno["banda"])["licenciada"], diseno["banda"])

        # 10. coherencia de la decisión: el elegido es el de menor costo entre los que cumplen
        if evaluados:
            ok_ev = [e for e in evaluados if e.get("cumple")]
            mejor = min(ok_ev, key=lambda e: (round(e["costo"], 6), -e["disponibilidad"]["ref"]["margen_efectivo_dB"]))
            v("Decisión coherente (mínimo costo que cumple)", mejor["id"] == diseno["id"],
              f"elegido {diseno['id']} (costo {diseno['costo']:.2f}); mejor según criterio {mejor['id']} "
              f"(costo {mejor['costo']:.2f}); {len(ok_ev)} de {len(evaluados)} variantes cumplen")

        nuevas = pz.verificaciones[n0:]
        fallos = [x for x in nuevas if not x.ok and x.critica]
        ok = not fallos
        return Resultado(self.nombre, ok, f"{len(nuevas)} comprobaciones, {len(fallos)} fallos críticos"
                         + ("" if ok else ": " + "; ".join(x.nombre for x in fallos)), {"fallos": [x.nombre for x in fallos]})
