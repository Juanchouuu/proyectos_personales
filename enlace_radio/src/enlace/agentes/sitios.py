"""Subagente de sitios: valida los emplazamientos reales y la geometría del trayecto."""
from __future__ import annotations

import math

from ..herramientas import geo
from .base import Agente, Pizarra, Resultado


class AgenteSitios(Agente):
    nombre = "sitios"
    rol = "Valida los dos emplazamientos reales: coordenadas, elevación (DEM), distancia, azimuts y justificación."
    herramientas = ["geo.distancia_km", "geo.azimut_deg", "dem.elevacion"]

    def ejecutar(self, pz: Pizarra, **_) -> Resultado:
        cfg = self.ctx.config
        req = cfg["requisitos"]
        sitios = {}
        for clave in ("A", "B"):
            s = dict(cfg["sitios"][clave])
            try:
                s["elev_m"] = self.ctx.dem.elevacion(s["lat"], s["lon"])
                s["fuente_elev"] = "SRTM 1\" (interpolación bilineal)"
            except Exception:  # sin red: se toma del perfil guardado
                from ..herramientas.dem import leer_perfil_csv
                perf = leer_perfil_csv(self.ctx.perfil_csv)
                s["elev_m"] = float(perf["h_m"][0] if clave == "A" else perf["h_m"][-1])
                s["fuente_elev"] = "perfil SRTM guardado (data/perfil_terreno.csv)"
            s["lat_dms"] = geo.formato_dms(s["lat"], True)
            s["lon_dms"] = geo.formato_dms(s["lon"], False)
            sitios[clave] = s
            pz.verificar(self.nombre, f"Elevación válida sitio {clave}", 0 < s["elev_m"] < 6000 and not math.isnan(s["elev_m"]),
                         f"{s['elev_m']:.1f} m s. n. m.")
        A, B = sitios["A"], sitios["B"]
        d = geo.distancia_km(A["lat"], A["lon"], B["lat"], B["lon"])
        azAB = geo.azimut_deg(A["lat"], A["lon"], B["lat"], B["lon"])
        azBA = geo.azimut_deg(B["lat"], B["lon"], A["lat"], A["lon"])
        ok_d = abs(d - req["distancia_objetivo_km"]) <= req["tolerancia_distancia_km"]
        pz.verificar(self.nombre, "Distancia cercana a la especificada",
                     ok_d, f"d = {d:.2f} km (objetivo {req['distancia_objetivo_km']} ± {req['tolerancia_distancia_km']} km)")
        for k, v in sitios.items():
            pz.escribir(f"sitio_{k}", v, self.nombre)
        pz.escribir("distancia_km", d, self.nombre, "km", "Haversine sobre esfera de radio 6371 km")
        pz.escribir("azimut_AB_deg", azAB, self.nombre, "°", "norte verdadero")
        pz.escribir("azimut_BA_deg", azBA, self.nombre, "°", "norte verdadero")
        pz.fuente("Coordenadas", "Coordenadas WGS84 elegidas sobre cartografía abierta (OpenStreetMap) y verificadas con SRTM")
        pz.fuente("DEM", self.ctx.config["dem"]["fuente"])
        return Resultado(self.nombre, ok_d, f"d = {d:.2f} km, azimut A->B = {azAB:.1f}°, "
                         f"elevaciones {A['elev_m']:.0f} / {B['elev_m']:.0f} m s. n. m.", {"d_km": d})
