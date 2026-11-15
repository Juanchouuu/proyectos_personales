"""Subagente de terreno: perfil real, línea de vista, zona de Fresnel y alturas de antena."""
from __future__ import annotations

import numpy as np

from ..herramientas import dem as demmod
from ..herramientas import propagacion as prop
from .base import Agente, Pizarra, Resultado


class AgenteTerreno(Agente):
    nombre = "terreno"
    rol = ("Extrae el perfil del terreno del DEM, añade clutter y curvatura terrestre, verifica la línea de vista "
           "y el despeje de la 1.ª zona de Fresnel y calcula las alturas mínimas de antena.")
    herramientas = ["dem.perfil", "propagacion.analizar_despeje", "propagacion.alturas_minimas"]

    # ---- perfil -------------------------------------------------------------------------------
    def _perfil(self, pz: Pizarra) -> dict:
        A, B = pz.leer("sitio_A"), pz.leer("sitio_B")
        paso = self.ctx.config["dem"]["paso_muestreo_m"]
        try:
            perf = self.ctx.dem.perfil(A["lat"], A["lon"], B["lat"], B["lon"], paso)
            demmod.guardar_perfil_csv(perf, self.ctx.perfil_csv)
            origen = "SRTM 1\" descargado/caché (" + ", ".join(self.ctx.dem.teselas_usadas) + ")"
        except Exception as e:  # sin red
            perf = demmod.leer_perfil_csv(self.ctx.perfil_csv)
            origen = f"perfil guardado data/perfil_terreno.csv (sin acceso al DEM: {type(e).__name__})"
        d = perf["d_km"]
        clutter = np.zeros_like(d)
        for t in self.ctx.config["clutter"]["tramos"]:
            clutter[(d >= t["desde_km"]) & (d < t["hasta_km"])] = t["altura_m"]
        clutter[0] = clutter[-1] = 0.0
        perf["clutter_m"] = clutter
        perf["origen"] = origen
        return perf

    def ejecutar(self, pz: Pizarra, tarea: str = "perfil", f_GHz: float | None = None, **_) -> Resultado:
        if tarea == "perfil":
            perf = self._perfil(pz)
            pz.escribir("perfil", perf, self.nombre, "km / m", perf["origen"])
            h = perf["h_m"]
            ok = bool(np.all(np.isfinite(h)))
            pz.verificar(self.nombre, "Perfil sin huecos de datos", ok, f"{len(h)} muestras cada "
                         f"{self.ctx.config['dem']['paso_muestreo_m']:.0f} m")
            pz.verificar(self.nombre, "Perfil coherente con elevaciones de los sitios",
                         abs(h[0] - pz.leer("sitio_A")["elev_m"]) < 5 and abs(h[-1] - pz.leer("sitio_B")["elev_m"]) < 5,
                         f"extremos {h[0]:.1f} / {h[-1]:.1f} m")
            pz.supuesto(self.nombre, "Clutter: " + "; ".join(f"{t['desde_km']:.1f}-{t['hasta_km']:.1f} km: "
                        f"{t['altura_m']:.0f} m ({t['tipo']})" for t in self.ctx.config["clutter"]["tramos"]))
            # línea de vista geométrica con antenas mínimas de referencia
            A = pz.leer("sitio_A")
            geo_ = prop.analizar_despeje(perf["d_km"], perf["h_m"], perf["clutter_m"],
                                         A["altura_estructura_existente_m"], 10.0, 7.5, 4 / 3)
            pz.escribir("los_referencia", geo_, self.nombre)
            return Resultado(self.nombre, ok, f"perfil de {len(h)} puntos; cota máx. {np.nanmax(h):.0f} m, "
                             f"mín. {np.nanmin(h):.0f} m; origen: {perf['origen']}")

        if tarea == "alturas":
            cache = pz.leer("alturas_cache", {})
            clave = round(f_GHz, 3)
            if clave in cache:
                r = cache[clave]
                return Resultado(self.nombre, r is not None, "alturas en caché")
            perf = pz.leer("perfil")
            crit = self.ctx.config["criterios_despeje"]
            criterios = [(crit["k_mediano"]["k"], crit["k_mediano"]["fraccion_F1"]),
                         (crit["k_minimo"]["k"], crit["k_minimo"]["fraccion_F1"])]
            A, B = self.ctx.config["sitios"]["A"], self.ctx.config["sitios"]["B"]
            hmin_A = A.get("altura_min_m", A["altura_estructura_existente_m"] + 3.0)
            hmin_B = B.get("altura_min_m", max(B["altura_estructura_existente_m"], 6.0))
            alt = prop.alturas_minimas(perf["d_km"], perf["h_m"], perf["clutter_m"], f_GHz, criterios,
                                       hmin_A, A["altura_max_mastil_m"], hmin_B, B["altura_max_mastil_m"])
            if alt is None:
                cache[clave] = None
                pz.escribir("alturas_cache", cache, self.nombre)
                return Resultado(self.nombre, False, f"sin alturas factibles a {f_GHz} GHz dentro de los límites")
            det = {}
            for nombre, (k, frac) in zip(("k_mediano", "k_minimo"), criterios):
                a = prop.analizar_despeje(perf["d_km"], perf["h_m"], perf["clutter_m"], alt["hA_m"], alt["hB_m"], f_GHz, k)
                det[nombre] = {"k": k, "fraccion_exigida": frac, "despeje_rel_min": a["despeje_rel_min"],
                               "d_critico_km": a["d_critico_km"], "despeje_min_m": a["despeje_min_m"],
                               "f1_critico_m": a["f1_critico_m"]}
            r = {**alt, "detalle": det, "criterios": criterios}
            cache[clave] = r
            pz.escribir("alturas_cache", cache, self.nombre)
            return Resultado(self.nombre, True, f"f = {f_GHz} GHz: hA = {alt['hA_m']:.0f} m, hB = {alt['hB_m']:.0f} m "
                             f"(h/F1 = {det['k_mediano']['despeje_rel_min']:.2f} con k=4/3; "
                             f"{det['k_minimo']['despeje_rel_min']:.2f} con k=2/3)", r)
        raise ValueError(tarea)
