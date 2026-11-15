"""Subagente de interferencias: escenarios cocanal, plan de frecuencias y mitigación."""
from __future__ import annotations

from ..herramientas import interferencia as itf
from .base import Agente, Pizarra, Resultado


class AgenteInterferencias(Agente):
    nombre = "interferencias"
    rol = ("Evalúa la interferencia cocanal con diagramas ITU-R F.699, calcula I/N, C/I y la degradación del umbral; "
           "si un escenario no cumple, aplica el plan de frecuencias (polarización cruzada y luego canal adyacente).")
    herramientas = ["interferencia.ganancia_fuera_eje_dBi", "interferencia.evaluar_escenario"]

    def ejecutar(self, pz: Pizarra, diseno: dict, **_) -> Resultado:
        cfg = self.ctx.config["interferencia"]
        cat = self.ctx.catalogo
        pres = diseno["presupuesto"]
        ref = pres["ref"]
        nf = cat.radio["figura_ruido_dB"]
        xpd = cat.antena(diseno["antena_m"])["XPD_dB"]
        nfd = cat.radio["NFD_canal_adyacente_dB"]
        ef = cat.antena(diseno["antena_m"])["eficiencia"]
        res = []
        for esc in cfg["escenarios"]:
            def ev(e):
                return itf.evaluar_escenario(e, diseno["f_GHz"], pres["G_dBi"], diseno["antena_m"], pres["Lr_dB"],
                                             diseno["ancho_MHz"], nf, ref["prx_dBm"], ref["snr_dB"], ef)
            r = ev(esc)
            r["cocanal_I_N_dB"] = r["I_N_dB"]
            r["mitigacion"] = "ninguna (cocanal)"
            if not r["cumple"]:
                e2 = dict(esc)
                pasos = []
                if esc.get("discriminacion_polarizacion_dB", 0.0) == 0.0:
                    e2["discriminacion_polarizacion_dB"] = xpd
                    pasos.append(f"polarización cruzada (XPD {xpd:.0f} dB)")
                    r2 = ev(e2)
                else:
                    r2 = r
                if not r2["cumple"]:
                    e2["discriminacion_polarizacion_dB"] = e2.get("discriminacion_polarizacion_dB", 0.0) + nfd
                    pasos.append(f"canal adyacente (NFD {nfd:.0f} dB)")
                    r2 = ev(e2)
                r2["cocanal_I_N_dB"] = r["I_N_dB"]
                r2["mitigacion"] = " + ".join(pasos)
                r = r2
            res.append(r)
        td = max(x["degradacion_umbral_dB"] for x in res)
        ok = all(x["cumple"] for x in res)
        diseno["interferencia"] = {"escenarios": res, "degradacion_max_dB": td, "cumple": ok}
        pz.fuente("Interferencias", cfg["fuente"])
        if not ok:
            diseno.setdefault("motivos", []).append("interferencia por encima del criterio aun con mitigación")
        mit = [x["nombre"] + ": " + x["mitigacion"] for x in res if not x["mitigacion"].startswith("ninguna")]
        return Resultado(self.nombre, ok, f"{diseno['id']}: degradación máx. del umbral {td:.2f} dB"
                         + (f"; mitigación aplicada -> {'; '.join(mit)}" if mit else "")
                         + ("" if ok else "; NO cumple"), diseno["interferencia"])
