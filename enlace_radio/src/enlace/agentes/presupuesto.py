"""Subagente de presupuesto de enlace: PIRE, pérdidas, potencia recibida, margen y capacidad (ACM)."""
from __future__ import annotations

from ..herramientas import propagacion as prop
from .base import Agente, Pizarra, Resultado


class AgentePresupuesto(Agente):
    nombre = "presupuesto"
    rol = "Calcula el presupuesto de potencia por modulación (ACM), la capacidad y el margen de desvanecimiento."
    herramientas = ["propagacion.perdida_espacio_libre_dB", "propagacion.atenuacion_gases_dB_km",
                    "propagacion.ganancia_parabolica_dBi", "equipos.modulaciones"]

    def ejecutar(self, pz: Pizarra, diseno: dict, **_) -> Resultado:
        cat = self.ctx.catalogo
        clima = self.ctx.config["clima"]
        cap_req = self.ctx.config["requisitos"]["capacidad_minima_mbps"]
        d = pz.leer("distancia_km")
        f = diseno["f_GHz"]
        ant = cat.antena(diseno["antena_m"])
        G = prop.ganancia_parabolica_dBi(diseno["antena_m"], f, ant["eficiencia"])
        fspl = prop.perdida_espacio_libre_dB(d, f)
        go, gw = prop.atenuacion_gases_dB_km(f, clima["densidad_vapor_g_m3"])
        h_media = (pz.leer("sitio_A")["elev_m"] + pz.leer("sitio_B")["elev_m"]) / 2
        a_gas = (go * prop.factor_presion_altitud(h_media) + gw) * d
        Lt = Lr = cat.radio["perdidas_acople_dB"]
        Lvar = cat.radio["perdidas_varias_dB"]
        filas = []
        for m in cat.modulaciones(diseno["banda"], diseno["ancho_MHz"]):
            pire = m["ptx_dBm"] - Lt + G
            prx = pire - fspl - a_gas + G - Lr - Lvar
            filas.append({**m, "pire_dBm": pire, "prx_dBm": prx, "margen_dB": prx - m["umbral_dBm"]})
        ref = next((r for r in filas if r["capacidad_Mbps"] >= cap_req), None)
        maxima = None
        for r in filas:
            if r["margen_dB"] >= 0 and r["prx_dBm"] <= cat.radio["prx_max_dBm"]:
                maxima = r
        res = {
            "G_dBi": G, "ancho_haz_deg": prop.ancho_haz_deg(diseno["antena_m"], f), "FSPL_dB": fspl,
            "gamma_o_dB_km": go, "gamma_w_dB_km": gw, "A_gases_dB": a_gas, "Lt_dB": Lt, "Lr_dB": Lr,
            "Lvarias_dB": Lvar, "tabla": filas, "ref": ref, "max_cielo_despejado": maxima,
        }
        diseno["presupuesto"] = res
        if ref is None:
            diseno.setdefault("motivos", []).append("ninguna modulación alcanza la capacidad")
            return Resultado(self.nombre, False, "sin modulación para la capacidad requerida", res)
        ok = ref["margen_dB"] > 0
        if not ok:
            diseno.setdefault("motivos", []).append("Prx por debajo del umbral en cielo despejado")
        pz.supuesto(self.nombre, f"Pérdidas de acople {Lt} dB por extremo (radio full-outdoor) y {Lvar} dB de "
                    "desalineación y radomos; atenuación por gases según ITU-R P.676 (aproximación) con "
                    f"ρ = {clima['densidad_vapor_g_m3']} g/m³ y corrección de presión por altitud")
        return Resultado(self.nombre, ok, f"{diseno['id']}: G = {G:.1f} dBi, FSPL = {fspl:.1f} dB, Prx({ref['mod']}) = "
                         f"{ref['prx_dBm']:.1f} dBm, margen = {ref['margen_dB']:.1f} dB", res)
