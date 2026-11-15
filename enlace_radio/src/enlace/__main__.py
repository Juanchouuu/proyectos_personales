"""Punto de entrada: ``python -m enlace [opciones]``."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="enlace", description="Sistema multiagente de diseño de radioenlaces punto a punto")
    ap.add_argument("--config", default=str(RAIZ / "config" / "escenario.json"), help="escenario JSON")
    ap.add_argument("--salida", default=str(RAIZ / "salida"), help="carpeta de resultados")
    ap.add_argument("--motor", choices=["auto", "reglas", "claude"], default="auto",
                    help="orquestación: 'reglas' (determinista), 'claude' (agentes LLM) o 'auto' (claude si hay "
                         "ANTHROPIC_API_KEY)")
    ap.add_argument("--modelo", default=os.environ.get("ENLACE_MODELO", "claude-opus-5-5"), help="modelo de Claude")
    ap.add_argument("--sin-red", action="store_true", help="no descargar el DEM; usar el perfil guardado")
    ap.add_argument("-v", "--verbose", action="store_true", help="mostrar la traza de mensajes")
    a = ap.parse_args(argv)

    from .agentes.base import Contexto

    ctx = Contexto.crear(RAIZ, Path(a.config), Path(a.salida), sin_red=a.sin_red)
    motor = a.motor
    if motor == "auto":
        motor = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "reglas"
    if motor == "claude":
        from .llm import OrquestadorClaude

        orq = OrquestadorClaude(ctx, modelo=a.modelo)
    else:
        from .agentes.orquestador import Orquestador

        orq = Orquestador(ctx)
    sel = orq.ejecutar()
    if a.verbose:
        for m in orq.pz.mensajes:
            print(f"[{m.t:7.2f}s] {m.de:>20} -> {m.para:<22} {m.tipo:<12} {m.contenido}")
    d = sel["disponibilidad"]["ref"]
    print(f"Diseño seleccionado: {sel['id']} - {sel['descripcion']}")
    print(f"  alturas {sel['alturas']['hA_m']:.0f} m / {sel['alturas']['hB_m']:.0f} m · "
          f"{sel['presupuesto']['ref']['mod']} {sel['presupuesto']['ref']['capacidad_Mbps']:.0f} Mbps · "
          f"disponibilidad {d['disponibilidad_pct']:.4f} % · {'CUMPLE' if sel['cumple'] else 'NO CUMPLE'}")
    fallos = [v for v in orq.pz.verificaciones if not v.ok and v.critica]
    print(f"  verificaciones: {len(orq.pz.verificaciones)} ({len(fallos)} fallos críticos)")
    print(f"Informe: {orq.pz.leer('ruta_pdf')}")
    return 0 if sel["cumple"] and not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
