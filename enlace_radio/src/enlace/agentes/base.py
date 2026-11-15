"""Infraestructura común: pizarra compartida, mensajes, verificaciones y clase base de agente."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..herramientas.dem import DEM
from ..herramientas.equipos import Catalogo


@dataclass
class Dato:
    clave: str
    valor: Any
    autor: str
    unidad: str = ""
    fuente: str = ""


@dataclass
class Mensaje:
    t: float
    de: str
    para: str
    tipo: str          # solicitud | resultado | verificacion | decision | alerta
    contenido: str


@dataclass
class Verificacion:
    agente: str
    nombre: str
    ok: bool
    detalle: str
    critica: bool = True


class Pizarra:
    """Memoria compartida (patrón *blackboard*). Cada dato guarda autor, unidad y fuente."""

    def __init__(self):
        self.datos: dict[str, Dato] = {}
        self.mensajes: list[Mensaje] = []
        self.verificaciones: list[Verificacion] = []
        self.supuestos: list[tuple[str, str]] = []
        self.fuentes: dict[str, str] = {}
        self._t0 = time.time()

    def escribir(self, clave: str, valor: Any, autor: str, unidad: str = "", fuente: str = "") -> None:
        self.datos[clave] = Dato(clave, valor, autor, unidad, fuente)

    def leer(self, clave: str, defecto: Any = None) -> Any:
        d = self.datos.get(clave)
        return defecto if d is None else d.valor

    def __contains__(self, clave: str) -> bool:
        return clave in self.datos

    def mensaje(self, de: str, para: str, tipo: str, contenido: str) -> None:
        self.mensajes.append(Mensaje(round(time.time() - self._t0, 3), de, para, tipo, contenido))

    def verificar(self, agente: str, nombre: str, ok: bool, detalle: str, critica: bool = True) -> bool:
        self.verificaciones.append(Verificacion(agente, nombre, bool(ok), detalle, critica))
        return bool(ok)

    def supuesto(self, agente: str, texto: str) -> None:
        if (agente, texto) not in self.supuestos:
            self.supuestos.append((agente, texto))

    def fuente(self, clave: str, texto: str) -> None:
        self.fuentes[clave] = texto

    def resumen_json(self) -> str:
        """Vista compacta (escalares) para el motor LLM o para depuración."""
        out = {}
        for k, d in self.datos.items():
            if isinstance(d.valor, (int, float, str, bool)) or d.valor is None:
                out[k] = d.valor
        return json.dumps(out, ensure_ascii=False, default=str)


@dataclass
class Contexto:
    """Recursos compartidos por todos los agentes."""
    raiz: Path
    config: dict
    catalogo: Catalogo
    dem: DEM
    salida: Path
    perfil_csv: Path
    opciones: dict = field(default_factory=dict)

    @classmethod
    def crear(cls, raiz: Path, ruta_config: Path, salida: Path, sin_red: bool = False) -> "Contexto":
        config = json.loads(Path(ruta_config).read_text(encoding="utf-8"))
        catalogo = Catalogo(raiz / "data" / "equipos.json")
        dem = DEM(raiz / "data" / "dem", url=config["dem"]["url_plantilla"], descargar=not sin_red)
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "figuras").mkdir(exist_ok=True)
        return cls(raiz, config, catalogo, dem, salida, raiz / "data" / "perfil_terreno.csv")


@dataclass
class Resultado:
    agente: str
    ok: bool
    resumen: str
    datos: dict = field(default_factory=dict)


class Agente:
    nombre = "agente"
    rol = ""
    herramientas: list[str] = []

    def __init__(self, ctx: Contexto):
        self.ctx = ctx

    def ejecutar(self, pz: Pizarra, **params) -> Resultado:  # pragma: no cover - interfaz
        raise NotImplementedError

    def __call__(self, pz: Pizarra, solicitante: str = "orquestador", **params) -> Resultado:
        pz.mensaje(solicitante, self.nombre, "solicitud", _describir(params))
        res = self.ejecutar(pz, **params)
        pz.mensaje(self.nombre, solicitante, "resultado", ("OK: " if res.ok else "NO CUMPLE: ") + res.resumen)
        return res


def _describir(params: dict) -> str:
    if not params:
        return "ejecutar tarea"
    partes = []
    for k, v in params.items():
        if isinstance(v, dict) and "id" in v:
            partes.append(f"{k}={v['id']}")
        elif isinstance(v, (int, float, str)):
            partes.append(f"{k}={v}")
        else:
            partes.append(k)
    return "ejecutar con " + ", ".join(partes)
