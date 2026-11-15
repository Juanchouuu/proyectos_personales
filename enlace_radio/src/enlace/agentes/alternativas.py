"""Subagente de alternativas: genera variantes técnicas cuando un diseño no cumple."""
from __future__ import annotations

from .base import Agente, Pizarra, Resultado


class AgenteAlternativas(Agente):
    nombre = "alternativas"
    rol = ("Propone variantes técnicas cuando el diseño no cumple: antenas mayores, canal más ancho, "
           "bandas más bajas y otra polarización. También estima su costo relativo.")
    herramientas = ["equipos.Catalogo"]

    def ejecutar(self, pz: Pizarra, base: dict, **_) -> Resultado:
        cat = self.ctx.catalogo
        variantes = []
        n = 0
        for b in sorted(cat.bandas, key=lambda x: -x["f_GHz"]):
            if not b["licenciada"]:
                continue
            for ancho in b["anchos_MHz"]:
                for ant in cat.antenas:
                    if ant["diametro_m"] < 0.6:
                        continue
                    for pol in ("V", "H"):
                        clave = (b["banda"], ancho, ant["diametro_m"], pol)
                        if clave == (base["banda"], base["ancho_MHz"], base["antena_m"], base["pol"]):
                            continue
                        n += 1
                        familia = []
                        if b["banda"] != base["banda"]:
                            familia.append("cambio de banda")
                        if ancho != base["ancho_MHz"]:
                            familia.append("canal más ancho")
                        if ant["diametro_m"] != base["antena_m"]:
                            familia.append("antenas mayores" if ant["diametro_m"] > base["antena_m"] else "antenas menores")
                        if pol != base["pol"]:
                            familia.append("polarización H")
                        variantes.append({
                            "id": f"A{n:03d}", "origen": "alternativa", "banda": b["banda"], "f_GHz": b["f_GHz"],
                            "ancho_MHz": ancho, "pol": pol, "antena_m": ant["diametro_m"],
                            "familia": ", ".join(familia),
                            "descripcion": f"{b['banda']}, {ancho} MHz, pol. {pol}, antenas de {ant['diametro_m']} m",
                        })
        pz.escribir("alternativas_propuestas", len(variantes), self.nombre)
        pz.supuesto(self.nombre, "Alternativas no cuantificadas en detalle: salto con repetidor (innecesario si alguna "
                    "variante directa cumple) y diversidad de espacio (el multitrayecto no es dominante a esta "
                    "distancia y altitud)")
        return Resultado(self.nombre, True, f"{len(variantes)} variantes generadas a partir de {base['id']} "
                         "(banda x canal x antena x polarización)", {"variantes": variantes})

    def costo(self, diseno: dict) -> float:
        c = self.ctx.catalogo.datos["costos"]
        ant = self.ctx.catalogo.antena(diseno["antena_m"])["costo_relativo"]
        alt = diseno.get("alturas") or {"hA_m": 0, "hB_m": 0}
        return (self.ctx.catalogo.radio["costo_relativo_por_par"] + 2 * ant
                + c["torre_por_metro"] * (alt["hA_m"] + alt["hB_m"]) + c["espectro_por_MHz"] * diseno["ancho_MHz"])
