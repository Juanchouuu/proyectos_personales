"""Subagente de disponibilidad: lluvia (ITU-R P.530/P.838), multitrayecto (P.530) y objetivo 99,99 %."""
from __future__ import annotations

from ..herramientas import itur
from .base import Agente, Pizarra, Resultado


class AgenteDisponibilidad(Agente):
    nombre = "disponibilidad"
    rol = ("Calcula la indisponibilidad por lluvia y la probabilidad de corte por multitrayecto para la modulación "
           "que garantiza la capacidad mínima, y la curva capacidad-disponibilidad con ACM.")
    herramientas = ["itur.atenuacion_lluvia_001", "itur.porcentaje_excedido_lluvia", "itur.multitrayecto"]

    def ejecutar(self, pz: Pizarra, diseno: dict, **_) -> Resultado:
        clima = self.ctx.config["clima"]
        req = self.ctx.config["requisitos"]
        d = pz.leer("distancia_km")
        f = diseno["f_GHz"]
        pres = diseno["presupuesto"]
        td = diseno.get("interferencia", {}).get("degradacion_max_dB", 0.0)
        lluvia = itur.atenuacion_lluvia_001(d, f, clima["R001_mm_h"], diseno["pol"])
        alt = diseno["alturas"]
        zA = pz.leer("sitio_A")["elev_m"] + alt["hA_m"]
        zB = pz.leer("sitio_B")["elev_m"] + alt["hB_m"]
        objetivo = 100 - req["disponibilidad_objetivo_pct"]

        def evaluar(fila):
            m = fila["margen_dB"] - td
            if m <= 0:
                return {"margen_efectivo_dB": m, "p_lluvia_pct": 100.0, "p_multi_pct": 100.0, "p_total_pct": 100.0,
                        "disponibilidad_pct": 0.0}
            pl = itur.porcentaje_excedido_lluvia(lluvia["A001_dB"], m, f)
            mp = itur.multitrayecto(d, f, clima["dN1"], zA, zB, m)
            pt = pl + mp["pw_pct"]
            return {"margen_efectivo_dB": m, "p_lluvia_pct": pl, "p_multi_pct": mp["pw_pct"], "p_total_pct": pt,
                    "disponibilidad_pct": 100 - pt, "multitrayecto": mp}

        curva = []
        for fila in pres["tabla"]:
            e = evaluar(fila)
            curva.append({"mod": fila["mod"], "capacidad_Mbps": fila["capacidad_Mbps"], **{k: v for k, v in e.items()
                                                                                          if k != "multitrayecto"}})
        ref = evaluar(pres["ref"])
        cumple = ref["p_total_pct"] <= objetivo
        diseno["disponibilidad"] = {"lluvia": lluvia, "ref": ref, "curva_acm": curva, "objetivo_pct": objetivo,
                                    "A_lluvia_margen_dB": ref["margen_efectivo_dB"], "cumple": cumple,
                                    "extrapolado": ref["p_lluvia_pct"] < 1e-3}
        pz.supuesto(self.nombre, f"R0,01 = {clima['R001_mm_h']} mm/h ({clima['fuente_R001']})")
        pz.supuesto(self.nombre, f"dN1 = {clima['dN1']} ({clima['fuente_dN1']})")
        pz.supuesto(self.nombre, "La probabilidad de multitrayecto (mes más desfavorable) se suma a la indisponibilidad "
                    "anual por lluvia como criterio conservador; la degradación del umbral por interferencia se "
                    "descuenta del margen")
        if not cumple:
            diseno.setdefault("motivos", []).append(
                f"disponibilidad {ref['disponibilidad_pct']:.4f} % < {req['disponibilidad_objetivo_pct']} %")
        return Resultado(self.nombre, cumple, f"{diseno['id']}: A0,01 = {lluvia['A001_dB']:.1f} dB, margen efectivo "
                         f"{ref['margen_efectivo_dB']:.1f} dB, indisponibilidad {ref['p_total_pct']:.5f} % "
                         f"(lluvia {ref['p_lluvia_pct']:.5f} %, multitrayecto {ref['p_multi_pct']:.6f} %)",
                         diseno["disponibilidad"])
