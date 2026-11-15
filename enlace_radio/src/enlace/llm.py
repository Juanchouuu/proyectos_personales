"""Motor LLM: el orquestador es un agente Claude que usa a los subagentes como herramientas.

Claude decide el orden de las tareas, qué alternativas evaluar, cuál elegir y redacta el análisis.
Todas las cifras salen de las herramientas (subagentes de cálculo) y se guardan en la pizarra; el revisor
y un verificador numérico comprueban lo que Claude afirma antes de generar el PDF.

Bucle manual de *tool use* con el SDK oficial ``anthropic`` (Messages API).
"""
from __future__ import annotations

import json
import re

from .agentes.orquestador import Orquestador
from .agentes.redaccion import hechos

SISTEMA = """Eres el agente ORQUESTADOR de un sistema multiagente de ingeniería de radioenlaces.
Objetivo: diseñar y validar un enlace de microondas punto a punto entre los dos sitios configurados
(~28 km) que entregue al menos 200 Mbps con una disponibilidad anual de 99,99 %, y producir el informe PDF.

Reglas:
- No calcules nada de cabeza: cada cifra debe salir de una herramienta (subagente). Si necesitas un dato, pídelo.
- Flujo esperado: validar_sitios -> extraer_perfil -> proponer_diseno_inicial -> evaluar_diseno(inicial).
  Si no cumple, explica por qué, llama a generar_y_evaluar_alternativas y analiza el ranking. Puedes evaluar
  variantes concretas con evaluar_diseno.
- Elige el diseño que cumpla todos los requisitos con el menor costo relativo, salvo que justifiques técnicamente
  otra elección (p. ej., margen claramente mayor por un costo casi igual). Envíalo a revisar_diseno; si la revisión
  tiene fallos críticos, elige otro.
- Al final llama a generar_informe con tus textos en español técnico (sin markdown, puedes usar <b>…</b>).
  Usa solo cifras que hayan devuelto las herramientas: el verificador rechaza los textos con números que no
  aparezcan en los resultados. Si te los rechaza, corrige y vuelve a llamar.
- Sé conciso entre llamadas a herramientas."""

_PROP = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def _tool(nombre, desc, props=None, req=None):
    esquema = {"type": "object", "properties": props or {}, "required": req or [], "additionalProperties": False}
    return {"name": nombre, "description": desc, "input_schema": esquema, "strict": True}


HERRAMIENTAS = [
    _tool("validar_sitios", "Subagente de sitios: valida coordenadas reales, elevación SRTM, distancia y azimuts."),
    _tool("extraer_perfil", "Subagente de terreno: extrae el perfil del DEM SRTM y añade el clutter."),
    _tool("proponer_diseno_inicial", "Subagente de frecuencia y equipos: propone el diseño inicial (banda, canal, "
          "polarización, antenas)."),
    _tool("evaluar_diseno", "Evalúa un diseño con la cadena terreno (alturas) -> presupuesto -> interferencias -> "
          "disponibilidad. Devuelve un resumen con el id asignado.",
          {"banda": {"type": "string", "enum": ["7 GHz", "8 GHz", "11 GHz", "13 GHz", "15 GHz", "18 GHz", "23 GHz"]},
           "ancho_MHz": {"type": "integer", "enum": [28, 56]},
           "pol": {"type": "string", "enum": ["V", "H"]},
           "antena_m": {"type": "number", "enum": [0.6, 0.9, 1.2, 1.8]}},
          ["banda", "ancho_MHz", "pol", "antena_m"]),
    _tool("generar_y_evaluar_alternativas", "Subagente de alternativas: genera todas las variantes "
          "(banda x canal x antena x polarización) a partir del diseño inicial, las evalúa y devuelve el ranking."),
    _tool("revisar_diseno", "Subagente revisor: verificación independiente del diseño indicado.",
          {"id": {"type": "string"}}, ["id"]),
    _tool("seleccionar_diseno", "Fija el diseño final (debe cumplir y haber pasado la revisión).",
          {"id": {"type": "string"}, "justificacion": {"type": "string"}}, ["id", "justificacion"]),
    _tool("generar_informe", "Subagente de informe: genera el PDF. Los textos se verifican numéricamente.",
          {"resumen": {"type": "string", "description": "Resumen ejecutivo (1-2 párrafos)"},
           "terreno": {"type": "string", "description": "Análisis de perfil, LOS y Fresnel"},
           "frecuencia": {"type": "string", "description": "Justificación de banda, canal, polarización y equipos"},
           "presupuesto": {"type": "string", "description": "Análisis del presupuesto de enlace"},
           "interferencias": {"type": "string", "description": "Análisis de interferencias"},
           "disponibilidad": {"type": "string", "description": "Análisis de capacidad y disponibilidad"},
           "conclusiones": {"type": "array", "items": {"type": "string"}},
           "recomendaciones": {"type": "array", "items": {"type": "string"}}},
          ["resumen", "terreno", "frecuencia", "presupuesto", "interferencias", "disponibilidad", "conclusiones",
           "recomendaciones"]),
]


# ---- verificación numérica de los textos ---------------------------------------------------------
_NUM = re.compile(r"(?<![\w.,])[-−]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d])|(?<![\w.,])[-−]?\d+(?:[.,]\d+)?")


def _a_float(tok: str) -> float:
    t = tok.replace("−", "-")
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):  # 2.600 o 1.234,5
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    return float(t)


def _valores(obj, acc: list[float]) -> list[float]:
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _valores(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _valores(v, acc)
    elif isinstance(obj, str):
        for tok in _NUM.findall(obj):
            try:
                acc.append(_a_float(tok))
            except ValueError:
                pass
    return acc


def verificar_cifras(textos: dict, referencias) -> list[str]:
    """Devuelve los números citados en los textos que no se encuentran en los resultados (tolerancia de redondeo)."""
    ref = _valores(referencias, [])
    ref += [100 - x for x in ref if 90 < x < 100]  # indisponibilidad <-> disponibilidad
    ref += [x / 100 for x in ref] + [x * 100 for x in ref] + [x * 525960 / 100 for x in ref if x < 1]
    malos = []
    for clave, txt in textos.items():
        for tok in _NUM.findall(" ".join(txt) if isinstance(txt, list) else txt):
            try:
                x = _a_float(tok)
            except ValueError:
                continue
            if abs(x) <= 10 and float(x).is_integer():
                continue  # ordinales, enumeraciones, "2 extremos"...
            # la cifra debe coincidir con algún resultado redondeado a la precisión con que se cita
            dec = len(re.split(r"[.,]", tok.replace(".", "") if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", tok) else tok)[1]) \
                if re.search(r"[.,]\d+$", tok) and not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", tok) else 0
            tol = 0.5 * 10 ** -dec + 1e-9
            if any(abs(x - r) <= max(tol, 0.001 * abs(r)) for r in ref):
                continue
            malos.append(f"{clave}: {tok}")
    return malos


# ---- orquestador LLM -----------------------------------------------------------------------------
class OrquestadorClaude(Orquestador):
    rol = ("Agente LLM (Claude) que planifica el flujo, delega en los subagentes vía herramientas, interpreta los "
           "resultados, decide alternativas y selección, y redacta el análisis del informe.")

    def __init__(self, ctx, modelo: str = "claude-opus-5-5", cliente=None, max_iter: int = 40, esfuerzo: str = "high"):
        super().__init__(ctx)
        self.modelo = modelo
        self.max_iter = max_iter
        self.esfuerzo = esfuerzo
        self.motor = f"LLM Claude ({modelo}) + subagentes de cálculo + verificación numérica"
        if cliente is None:
            import anthropic

            cliente = anthropic.Anthropic()
        self.cliente = cliente
        self.revisados: dict[str, bool] = {}
        self.final: dict | None = None
        self.informe_ok = False
        self._n_manual = 0

    # ---- herramientas -----------------------------------------------------------------------
    def _resumen(self, d: dict) -> dict:
        if "disponibilidad" not in d:
            return {"id": d["id"], "descripcion": d["descripcion"], "cumple": False, "motivos": d.get("motivos", [])}
        ref = d["presupuesto"]["ref"]
        return {"id": d["id"], "descripcion": d["descripcion"], "cumple": d["cumple"], "motivos": d.get("motivos", []),
                "alturas_m": [d["alturas"]["hA_m"], d["alturas"]["hB_m"]], "ganancia_dBi": round(d["presupuesto"]["G_dBi"], 2),
                "modulacion_200Mbps": ref["mod"], "capacidad_Mbps": ref["capacidad_Mbps"], "prx_dBm": round(ref["prx_dBm"], 2),
                "margen_dB": round(ref["margen_dB"], 2), "degradacion_interf_dB": round(d["interferencia"]["degradacion_max_dB"], 2),
                "margen_efectivo_dB": round(d["disponibilidad"]["ref"]["margen_efectivo_dB"], 2),
                "A001_lluvia_dB": round(d["disponibilidad"]["lluvia"]["A001_dB"], 2),
                "indisp_lluvia_pct": d["disponibilidad"]["ref"]["p_lluvia_pct"],
                "indisp_multitrayecto_pct": d["disponibilidad"]["ref"]["p_multi_pct"],
                "disponibilidad_pct": round(d["disponibilidad"]["ref"]["disponibilidad_pct"], 5),
                "costo_relativo": round(d["costo"], 3)}

    def _buscar(self, id_: str) -> dict:
        for e in self.evaluados:
            if e["id"] == id_:
                return e
        raise KeyError(f"no existe un diseño evaluado con id {id_}")

    def ejecutar_herramienta(self, nombre: str, args: dict):
        pz = self.pz
        if nombre == "validar_sitios":
            r = self.delegar("sitios")
            return {"ok": r.ok, "resumen": r.resumen, "sitio_A": {k: pz.leer("sitio_A")[k] for k in ("nombre", "lat", "lon", "elev_m")},
                    "sitio_B": {k: pz.leer("sitio_B")[k] for k in ("nombre", "lat", "lon", "elev_m")},
                    "distancia_km": round(pz.leer("distancia_km"), 3)}
        if nombre == "extraer_perfil":
            return {"ok": True, "resumen": self.delegar("terreno", tarea="perfil").resumen}
        if nombre == "proponer_diseno_inicial":
            r = self.delegar("frecuencia_equipos")
            self._inicial = r.datos
            return {"resumen": r.resumen, "diseno": {k: r.datos[k] for k in ("id", "banda", "ancho_MHz", "pol", "antena_m")}}
        if nombre == "evaluar_diseno":
            ini = getattr(self, "_inicial", None)
            if ini is not None and "cumple" not in ini and (args["banda"], args["ancho_MHz"], args["pol"], args["antena_m"]) == (
                    ini["banda"], ini["ancho_MHz"], ini["pol"], ini["antena_m"]):
                d = self.evaluar(ini)
                pz.escribir("diseno_inicial", d, self.nombre)
            else:
                existente = next((e for e in self.evaluados if (e["banda"], e["ancho_MHz"], e["pol"], e["antena_m"]) ==
                                  (args["banda"], args["ancho_MHz"], args["pol"], args["antena_m"])), None)
                if existente:
                    return self._resumen(existente)
                self._n_manual += 1
                b = self.ctx.catalogo.banda(args["banda"])
                if args["ancho_MHz"] not in b["anchos_MHz"]:
                    raise ValueError(f"{args['ancho_MHz']} MHz no está canalizado en {args['banda']} ({b['anchos_MHz']})")
                d = self.evaluar({"id": f"M{self._n_manual:02d}", "origen": "orquestador", "banda": args["banda"],
                                  "f_GHz": b["f_GHz"], "ancho_MHz": args["ancho_MHz"], "pol": args["pol"],
                                  "antena_m": args["antena_m"],
                                  "descripcion": f"{args['banda']}, {args['ancho_MHz']} MHz, pol. {args['pol']}, "
                                                 f"antenas de {args['antena_m']} m"})
            return self._resumen(d)
        if nombre == "generar_y_evaluar_alternativas":
            base = pz.leer("diseno_inicial")
            if base is None or "cumple" not in base:
                raise ValueError("primero evalúa el diseño inicial con evaluar_diseno")
            r = self.delegar("alternativas", base=base)
            vistos = {(e["banda"], e["ancho_MHz"], e["pol"], e["antena_m"]) for e in self.evaluados}
            for v in r.datos["variantes"]:
                if (v["banda"], v["ancho_MHz"], v["pol"], v["antena_m"]) not in vistos:
                    self.evaluar(v, silencioso=True)
            ok = sorted([e for e in self.evaluados if e["cumple"]], key=lambda e: e["costo"])
            no = sorted([e for e in self.evaluados if not e["cumple"] and "disponibilidad" in e],
                        key=lambda e: -e["disponibilidad"]["ref"]["disponibilidad_pct"])
            return {"evaluados": len(self.evaluados), "cumplen": len(ok),
                    "ranking_cumplen_por_costo": [self._resumen(e) for e in ok[:10]],
                    "mejores_que_no_cumplen": [self._resumen(e) for e in no[:5]]}
        if nombre == "revisar_diseno":
            d = self._buscar(args["id"])
            if not d.get("cumple"):
                raise ValueError(f"{d['id']} no cumple los requisitos; no se puede aprobar")
            r = self.delegar("revisor", diseno=d, evaluados=self.evaluados)
            self.revisados[d["id"]] = r.ok
            nuevas = [v for v in pz.verificaciones if v.agente == "revisor"][-25:]
            return {"aprobado": r.ok, "resumen": r.resumen,
                    "avisos_o_fallos": [f"{v.nombre}: {v.detalle}" for v in nuevas if not v.ok]}
        if nombre == "seleccionar_diseno":
            d = self._buscar(args["id"])
            if not self.revisados.get(d["id"]):
                raise ValueError(f"{d['id']} no ha superado revisar_diseno")
            self.final = d
            pz.escribir("diseno_final", d, self.nombre)
            pz.escribir("evaluados", self.evaluados, self.nombre)
            self.decidir(f"Diseño seleccionado: {d['id']} ({d['descripcion']}). Justificación: {args['justificacion']}")
            h = hechos(pz, self.ctx)
            return {"seleccionado": d["id"], "datos_para_redactar": {k: v for k, v in h.items()
                                                                     if isinstance(v, (int, float, str))}}
        if nombre == "generar_informe":
            if self.final is None:
                raise ValueError("primero selecciona el diseño con seleccionar_diseno")
            ok_ = sorted([e for e in self.evaluados if e.get("cumple")], key=lambda e: e["costo"])[:10]
            por_banda = {}
            for e in self.evaluados:
                if "disponibilidad" in e and (e["banda"] not in por_banda or e["disponibilidad"]["ref"]["disponibilidad_pct"]
                                              > por_banda[e["banda"]]["disponibilidad"]["ref"]["disponibilidad_pct"]):
                    por_banda[e["banda"]] = e
            refs = [hechos(pz, self.ctx), self.final, pz.leer("diseno_inicial"), self.ctx.config["requisitos"],
                    self.ctx.config["clima"], self.ctx.config["criterios_despeje"],
                    [self._resumen(e) for e in ok_ + list(por_banda.values())],
                    {k: v for k, v in pz.datos.items() if k in ("distancia_km", "azimut_AB_deg", "azimut_BA_deg")}]
            refs[-1] = {k: v.valor for k, v in refs[-1].items()}
            malos = verificar_cifras(args, refs)
            if malos:
                pz.verificar("verificador", "Cifras de la redacción LLM", False,
                             f"rechazada: {len(malos)} cifras sin respaldo ({', '.join(malos[:6])})", critica=False)
                raise ValueError("Cifras sin respaldo en los resultados de las herramientas: " + "; ".join(malos[:20])
                                 + ". Corrige esos valores usando solo datos devueltos y vuelve a llamar.")
            pz.verificar("verificador", "Cifras de la redacción LLM", True,
                         "todas las cifras citadas por el LLM coinciden con resultados de las herramientas")
            r = self.delegar("informe", orquestador=self, textos=args)
            self.informe_ok = True
            return {"ok": True, "resumen": r.resumen}
        raise ValueError(f"herramienta desconocida: {nombre}")

    # ---- bucle agéntico -------------------------------------------------------------------------
    def _llamar(self, mensajes: list) -> object:
        return self.cliente.beta.messages.create(
            model=self.modelo, max_tokens=16000, system=SISTEMA, tools=HERRAMIENTAS, messages=mensajes,
            thinking={"type": "adaptive"}, output_config={"effort": self.esfuerzo},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")

    def ejecutar(self, generar_pdf: bool = True) -> dict:
        pz = self.pz
        req = self.ctx.config["requisitos"]
        self.decidir(f"Motor LLM ({self.modelo}): el orquestador Claude planifica y delega. Requisitos: "
                     f"{req['capacidad_minima_mbps']:.0f} Mbps, {req['disponibilidad_objetivo_pct']} %")
        mensajes = [{"role": "user", "content":
                     f"Diseña el enlace del escenario: {self.ctx.config['proyecto']}. Requisitos: "
                     f"{json.dumps(req, ensure_ascii=False)}. Empieza."}]
        for _ in range(self.max_iter):
            resp = self._llamar(mensajes)
            texto = " ".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            if texto:
                pz.mensaje("orquestador (Claude)", "pizarra", "razonamiento", texto[:600])
            if resp.stop_reason == "refusal":
                pz.mensaje(self.nombre, "pizarra", "alerta", "el modelo rechazó la solicitud")
                break
            if resp.stop_reason == "pause_turn":
                mensajes.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "max_tokens":
                mensajes.append({"role": "assistant", "content": resp.content})
                mensajes.append({"role": "user", "content": "Continúa; sé más breve."})
                continue
            usos = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if resp.stop_reason != "tool_use" or not usos:
                if self.informe_ok:
                    break
                mensajes.append({"role": "assistant", "content": resp.content})
                mensajes.append({"role": "user", "content": "Aún no se ha generado el informe: completa el flujo y "
                                                            "llama a generar_informe."})
                continue
            mensajes.append({"role": "assistant", "content": resp.content})
            resultados = []
            for u in usos:
                try:
                    salida = self.ejecutar_herramienta(u.name, dict(u.input))
                    resultados.append({"type": "tool_result", "tool_use_id": u.id,
                                       "content": json.dumps(salida, ensure_ascii=False, default=str)})
                except Exception as e:  # el error vuelve al modelo para que corrija
                    pz.mensaje(self.nombre, u.name, "alerta", f"error: {e}")
                    resultados.append({"type": "tool_result", "tool_use_id": u.id, "content": f"Error: {e}",
                                       "is_error": True})
            mensajes.append({"role": "user", "content": resultados})
        else:
            pz.mensaje(self.nombre, "pizarra", "alerta", f"se alcanzó el límite de {self.max_iter} iteraciones")

        if not self.informe_ok:  # salvaguarda: completar con el motor de reglas para no dejar al usuario sin informe
            self.decidir("El orquestador LLM no terminó el flujo: se completa con el motor de reglas")
            self.motor += " (completado por el motor de reglas)"
            if self.final is None:
                if pz.leer("diseno_inicial") is None or "cumple" not in pz.leer("diseno_inicial"):
                    return super().ejecutar(generar_pdf)
                cand = sorted([e for e in self.evaluados if e.get("cumple")], key=lambda e: e["costo"])
                if not cand:
                    return super().ejecutar(generar_pdf)
                self.final = cand[0]
                self.delegar("revisor", diseno=self.final, evaluados=self.evaluados)
                pz.escribir("diseno_final", self.final, self.nombre)
                pz.escribir("evaluados", self.evaluados, self.nombre)
            if generar_pdf:
                self.delegar("informe", orquestador=self)
        return self.final
