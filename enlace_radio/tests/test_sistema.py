import json
from pathlib import Path
from types import SimpleNamespace

from conftest import RAIZ
from enlace.agentes.base import Contexto
from enlace.agentes.orquestador import Orquestador
from enlace.llm import OrquestadorClaude, verificar_cifras


def _ctx(tmp_path):
    return Contexto.crear(RAIZ, RAIZ / "config" / "escenario.json", tmp_path, sin_red=True)


def test_flujo_reglas(tmp_path):
    o = Orquestador(_ctx(tmp_path))
    sel = o.ejecutar(generar_pdf=False)
    assert sel["cumple"]
    assert sel["presupuesto"]["ref"]["capacidad_Mbps"] >= 200
    assert sel["disponibilidad"]["ref"]["disponibilidad_pct"] >= 99.99
    assert not [v for v in o.pz.verificaciones if not v.ok and v.critica]
    assert o.pz.leer("diseno_inicial")["id"] == "D0"
    # el diseño inicial no cumple y obliga a evaluar alternativas
    assert not o.pz.leer("diseno_inicial")["cumple"] and len(o.evaluados) > 50


def test_verificador_detecta_cifras_inventadas():
    refs = {"disp": 99.9939, "margen": 16.81, "fspl": 138.78}
    assert verificar_cifras({"a": "Disponibilidad de 99,9939 % y margen de 16,8 dB; FSPL 138,8 dB"}, refs) == []
    assert verificar_cifras({"a": "margen de 23,4 dB"}, refs) == ["a: 23,4"]


# ---- cliente Claude simulado (no llama a la API) ----------------------------------------------------
def _uso(nombre, args, i):
    return SimpleNamespace(type="tool_use", name=nombre, input=args, id=f"tu_{i}")


class ClienteFalso:
    """Reproduce la secuencia de decisiones de un orquestador LLM leyendo los resultados de las herramientas."""

    def __init__(self):
        self.paso = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.llamadas = []

    def _ultimo(self, messages):
        cont = messages[-1]["content"]
        return json.loads(cont[0]["content"]) if isinstance(cont, list) and not cont[0].get("is_error") else cont

    def create(self, **kw):
        self.llamadas.append(kw)
        assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
        m = kw["messages"]
        self.paso += 1
        p = self.paso
        seq = {1: ("validar_sitios", {}), 2: ("extraer_perfil", {}), 3: ("proponer_diseno_inicial", {})}
        if p in seq:
            return SimpleNamespace(content=[_uso(*seq[p], p)], stop_reason="tool_use")
        if p == 4:
            d = self._ultimo(m)["diseno"]
            return SimpleNamespace(content=[_uso("evaluar_diseno", {k: d[k] for k in ("banda", "ancho_MHz", "pol", "antena_m")}, p)],
                                   stop_reason="tool_use")
        if p == 5:
            assert self._ultimo(m)["cumple"] is False
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="El inicial no cumple por lluvia."),
                                            _uso("generar_y_evaluar_alternativas", {}, p)], stop_reason="tool_use")
        if p == 6:
            self.elegido = self._ultimo(m)["ranking_cumplen_por_costo"][0]["id"]
            return SimpleNamespace(content=[_uso("revisar_diseno", {"id": self.elegido}, p)], stop_reason="tool_use")
        if p == 7:
            assert self._ultimo(m)["aprobado"]
            return SimpleNamespace(content=[_uso("seleccionar_diseno", {"id": self.elegido, "justificacion": "menor costo"}, p)],
                                   stop_reason="tool_use")
        if p == 8:
            self.h = self._ultimo(m)["datos_para_redactar"]
            textos = self._textos(self.h, inventado=True)
            return SimpleNamespace(content=[_uso("generar_informe", textos, p)], stop_reason="tool_use")
        if p == 9:
            assert m[-1]["content"][0].get("is_error"), "el verificador debía rechazar la cifra inventada"
            return SimpleNamespace(content=[_uso("generar_informe", self._textos(self.h, inventado=False), p)],
                                   stop_reason="tool_use")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Informe generado.")], stop_reason="end_turn")

    @staticmethod
    def _textos(h, inventado):
        disp = f"{h['disp']:.4f}".replace(".", ",")
        return {"resumen": f"Diseño {h['fin_id']} con disponibilidad de {disp} %.",
                "terreno": f"Despeje mínimo {h['despeje_k43']:.2f} F1.", "frecuencia": f"Banda de {h['banda']}.",
                "presupuesto": f"Margen de {h['margen']:.1f} dB." if not inventado else "Margen de 47,3 dB.",
                "interferencias": "Sin problemas tras el plan de frecuencias.",
                "disponibilidad": f"A0,01 = {h['A001']:.1f} dB.", "conclusiones": ["Cumple."], "recomendaciones": ["Site survey."]}


def test_flujo_claude_simulado(tmp_path):
    o = OrquestadorClaude(_ctx(tmp_path), cliente=ClienteFalso())
    sel = o.ejecutar()
    assert o.informe_ok and sel["cumple"]
    assert (tmp_path / "informe_enlace_radio.pdf").stat().st_size > 100_000
    assert any(v.agente == "verificador" and not v.ok for v in o.pz.verificaciones)
    assert any(v.agente == "verificador" and v.ok for v in o.pz.verificaciones)
