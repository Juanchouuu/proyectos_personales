"""Subagente de frecuencia y equipos: propone banda, canal, polarización, radio y antenas."""
from __future__ import annotations

from ..herramientas import propagacion as prop
from .base import Agente, Pizarra, Resultado


class AgenteFrecuenciaEquipos(Agente):
    nombre = "frecuencia_equipos"
    rol = ("Selecciona la banda licenciada, el ancho de canal, la polarización, el radio y las antenas del diseño "
           "inicial a partir del catálogo y de las reglas de planificación por distancia.")
    herramientas = ["equipos.Catalogo", "equipos.modulacion_minima", "propagacion.ganancia_parabolica_dBi"]

    def ejecutar(self, pz: Pizarra, **_) -> Resultado:
        cat = self.ctx.catalogo
        d = pz.leer("distancia_km")
        cap = self.ctx.config["requisitos"]["capacidad_minima_mbps"]
        candidatas = [b for b in cat.bandas if b["licenciada"] and b["dist_tipica_max_km"] >= d]
        # Regla de planificación: la banda más alta que cubre la distancia (antenas pequeñas y bandas bajas
        # reservadas para saltos largos), con el canal más estrecho que da la capacidad.
        candidatas.sort(key=lambda b: -b["f_GHz"])
        for b in candidatas:
            for ancho in sorted(b["anchos_MHz"]):
                mod = cat.modulacion_minima(b["banda"], ancho, cap)
                if mod is None:
                    continue
                diseno = {
                    "id": "D0", "origen": "inicial", "banda": b["banda"], "f_GHz": b["f_GHz"], "ancho_MHz": ancho,
                    "pol": "V", "antena_m": 0.6,
                    "descripcion": f"{b['banda']}, canal {ancho} MHz, pol. V, antenas de 0,6 m",
                }
                pz.escribir("diseno_inicial", diseno, self.nombre)
                pz.supuesto(self.nombre, "Regla de planificación del diseño inicial: banda licenciada más alta cuyo "
                            "alcance típico cubre la distancia, canal más estrecho que alcanza la capacidad, "
                            "polarización vertical y antenas de 0,6 m")
                pz.fuente("Catálogo de equipos", cat.datos["nota"])
                g = prop.ganancia_parabolica_dBi(0.6, b["f_GHz"], cat.antena(0.6)["eficiencia"])
                return Resultado(self.nombre, True, f"diseño inicial {diseno['descripcion']} (G = {g:.1f} dBi, "
                                 f"modulación mínima {mod['mod']} para {cap:.0f} Mbps)", diseno)
        return Resultado(self.nombre, False, "ninguna banda del catálogo alcanza la capacidad requerida")
