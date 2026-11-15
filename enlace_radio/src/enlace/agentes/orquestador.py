"""Agente orquestador (motor de reglas): planifica, delega en los subagentes, decide y valida."""
from __future__ import annotations

import copy

from .alternativas import AgenteAlternativas
from .base import Contexto, Pizarra, Resultado
from .disponibilidad import AgenteDisponibilidad
from .frecuencia_equipos import AgenteFrecuenciaEquipos
from .informe import AgenteInforme
from .interferencias import AgenteInterferencias
from .presupuesto import AgentePresupuesto
from .revisor import AgenteRevisor
from .sitios import AgenteSitios
from .terreno import AgenteTerreno


class Orquestador:
    nombre = "orquestador"
    rol = ("Planifica el flujo de trabajo, delega cada tarea en el subagente especialista, integra los resultados en la "
           "pizarra, decide si el diseño cumple, solicita y compara alternativas, exige la revisión técnica y ordena "
           "la generación del informe.")

    def __init__(self, ctx: Contexto):
        self.ctx = ctx
        self.pz = Pizarra()
        self.agentes = {a.nombre: a for a in (
            AgenteSitios(ctx), AgenteTerreno(ctx), AgenteFrecuenciaEquipos(ctx), AgentePresupuesto(ctx),
            AgenteInterferencias(ctx), AgenteDisponibilidad(ctx), AgenteAlternativas(ctx), AgenteRevisor(ctx),
            AgenteInforme(ctx))}
        self.evaluados: list[dict] = []

    # ---- utilidades --------------------------------------------------------------------------
    def delegar(self, agente: str, **params) -> Resultado:
        return self.agentes[agente](self.pz, solicitante=self.nombre, **params)

    def decidir(self, texto: str) -> None:
        self.pz.mensaje(self.nombre, "pizarra", "decision", texto)

    def evaluar(self, diseno: dict, silencioso: bool = False) -> dict:
        """Cadena de evaluación de un diseño: alturas -> presupuesto -> interferencias -> disponibilidad."""
        d = diseno
        pz = self.pz
        if silencioso:  # para las alternativas solo se registra el resumen, no cada mensaje
            n = len(pz.mensajes)
        r = self.delegar("terreno", tarea="alturas", f_GHz=d["f_GHz"])
        if not r.ok:
            d.update(cumple=False, motivos=["sin despeje factible"], costo=float("inf"))
            return d
        d["alturas"] = copy.deepcopy(pz.leer("alturas_cache")[round(d["f_GHz"], 3)])
        self.delegar("presupuesto", diseno=d)
        if d["presupuesto"]["ref"] is None:
            d.update(cumple=False, costo=float("inf"))
            return d
        r_i = self.delegar("interferencias", diseno=d)
        r_d = self.delegar("disponibilidad", diseno=d)
        d["cumple"] = bool(r_i.ok and r_d.ok and d["presupuesto"]["ref"]["margen_dB"] > 0)
        d["costo"] = self.agentes["alternativas"].costo(d)
        if silencioso:
            del pz.mensajes[n:]
            pz.mensaje("cadena de evaluación", self.nombre, "resultado",
                       f"{d['id']} ({d['descripcion']}): {'cumple' if d['cumple'] else 'no cumple'}; "
                       f"disponibilidad {d['disponibilidad']['ref']['disponibilidad_pct']:.4f} %, costo {d['costo']:.2f}")
        self.evaluados.append(d)
        return d

    # ---- flujo principal ---------------------------------------------------------------------
    def ejecutar(self, generar_pdf: bool = True) -> dict:
        pz = self.pz
        req = self.ctx.config["requisitos"]
        self.decidir(f"Plan: validar sitios -> perfil -> diseño inicial -> evaluación -> alternativas si no cumple -> "
                     f"revisión -> informe. Requisitos: {req['capacidad_minima_mbps']:.0f} Mbps, "
                     f"{req['disponibilidad_objetivo_pct']} %, ~{req['distancia_objetivo_km']:.0f} km")
        r = self.delegar("sitios")
        if not r.ok:
            self.decidir("Los sitios no cumplen la distancia especificada: se detiene el diseño")
            raise RuntimeError(r.resumen)
        self.delegar("terreno", tarea="perfil")
        r = self.delegar("frecuencia_equipos")
        inicial = self.evaluar(r.datos)
        pz.escribir("diseno_inicial", inicial, self.nombre)
        if inicial["cumple"]:
            self.decidir(f"El diseño inicial {inicial['id']} cumple todos los requisitos")
            candidatos = [inicial]
        else:
            self.decidir(f"El diseño inicial {inicial['id']} NO cumple ({'; '.join(inicial.get('motivos', []))}). "
                         "Se solicitan alternativas")
            r = self.delegar("alternativas", base=inicial)
            for v in r.datos["variantes"]:
                self.evaluar(v, silencioso=True)
            candidatos = [e for e in self.evaluados if e["cumple"]]
            self.decidir(f"{len(candidatos)} de {len(self.evaluados)} diseños evaluados cumplen los requisitos")
        if not candidatos:
            self.decidir("Ninguna variante directa cumple: se recomienda estudiar un salto con repetidor")
            seleccion = max(self.evaluados, key=lambda e: e.get("disponibilidad", {}).get("ref", {}).get(
                "disponibilidad_pct", 0))
        else:
            orden = sorted(candidatos, key=lambda e: (round(e["costo"], 6), -e["disponibilidad"]["ref"]["margen_efectivo_dB"]))
            seleccion = None
            for intento, cand in enumerate(orden[:5], start=1):
                self.decidir(f"Candidato {intento}: {cand['id']} ({cand['descripcion']}), costo relativo {cand['costo']:.2f}. "
                             "Se envía a revisión técnica")
                rev = self.delegar("revisor", diseno=cand, evaluados=self.evaluados)
                if rev.ok:
                    seleccion = cand
                    break
                self.decidir(f"La revisión rechaza {cand['id']}: {rev.resumen}. Se pasa al siguiente candidato")
            if seleccion is None:
                seleccion = orden[0]
                self.decidir("Ningún candidato superó la revisión: el informe se emite con observaciones")
        pz.escribir("diseno_final", seleccion, self.nombre)
        pz.escribir("evaluados", self.evaluados, self.nombre)
        self.decidir(f"Diseño seleccionado: {seleccion['id']} ({seleccion['descripcion']}); "
                     f"hA = {seleccion['alturas']['hA_m']:.0f} m, hB = {seleccion['alturas']['hB_m']:.0f} m")
        if generar_pdf:
            self.delegar("informe", orquestador=self)
        return seleccion
