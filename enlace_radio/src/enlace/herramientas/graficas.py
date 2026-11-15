"""Gráficas del informe (matplotlib, sin interfaz)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LightSource  # noqa: E402

from . import itur  # noqa: E402
from . import propagacion as prop  # noqa: E402
from .interferencia import ganancia_fuera_eje_dBi  # noqa: E402

plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 150,
                     "savefig.bbox": "tight", "axes.spines.top": False, "axes.spines.right": False})
AZUL, ROJO, VERDE, GRIS, NARANJA = "#1f5fa8", "#c0392b", "#2e8b57", "#7f8c8d", "#e67e22"

POBLACIONES = {"Bogotá (centro)": (4.6097, -74.0817), "Chía": (4.8615, -74.0583), "Cajicá": (4.9183, -74.0275),
               "Zipaquirá": (5.0221, -74.0047), "Cota": (4.8094, -74.1033), "Sopó": (4.9075, -73.9383),
               "Tabio": (4.9167, -74.0967), "Aeródromo Guaymaral": (4.8125, -74.0650)}


def mapa(dem, A: dict, B: dict, ruta: Path) -> Path:
    lat_min, lat_max = min(A["lat"], B["lat"]) - 0.08, max(A["lat"], B["lat"]) + 0.10
    lon_c = (A["lon"] + B["lon"]) / 2
    lon_min, lon_max = lon_c - 0.20, lon_c + 0.20
    lats, lons, z = dem.rejilla(lat_min, lat_max, lon_min, lon_max, n=260)
    ls = LightSource(azdeg=315, altdeg=45)
    fig, ax = plt.subplots(figsize=(6.4, 6.6))
    rgb = ls.shade(z, cmap=plt.cm.terrain, vert_exag=3, blend_mode="soft", vmin=2400, vmax=3600)
    ax.imshow(rgb, extent=[lon_min, lon_max, lat_min, lat_max], aspect="auto", origin="upper")
    cs = ax.contour(lons, lats, z, levels=range(2600, 3700, 200), colors="k", linewidths=0.3, alpha=0.5)
    ax.clabel(cs, fontsize=6, fmt="%d")
    ax.plot([A["lon"], B["lon"]], [A["lat"], B["lat"]], "-", color=ROJO, lw=2, label="Trayecto del enlace")
    for s, et in ((A, "A: Central"), (B, "B: Sede rural")):
        ax.plot(s["lon"], s["lat"], "^", ms=10, color=ROJO, mec="k")
        ax.annotate(et, (s["lon"], s["lat"]), xytext=(8, 4), textcoords="offset points", fontsize=8, weight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8))
    for n, (la, lo) in POBLACIONES.items():
        if lat_min < la < lat_max and lon_min < lo < lon_max:
            ax.plot(lo, la, "o", ms=3, color="k")
            ax.annotate(n, (lo, la), xytext=(4, -9), textcoords="offset points", fontsize=7)
    ax.set_xlabel("Longitud (°)")
    ax.set_ylabel("Latitud (°)")
    ax.set_title("Mapa topográfico (SRTM 1\") y trayecto del enlace")
    ax.legend(loc="lower right", fontsize=7)
    ax.grid(False)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def perfil(perf: dict, alturas: dict, f_GHz: float, criterios, ruta: Path) -> Path:
    d, h, cl = perf["d_km"], perf["h_m"], perf["clutter_m"]
    fig, axs = plt.subplots(2, 1, figsize=(7.2, 6.4), sharex=True)
    for ax, (k, frac) in zip(axs, criterios):
        a = prop.analizar_despeje(d, h, cl, alturas["hA_m"], alturas["hB_m"], f_GHz, k)
        base = h + a["abultamiento_m"]
        ax.fill_between(d, h.min() - 20, base, color="#a67c52", alpha=0.85, label="Terreno + curvatura")
        ax.fill_between(d, base, base + cl, color=VERDE, alpha=0.35, label="Clutter")
        ax.plot(d, a["los_m"], color=ROJO, lw=1.3, label="Línea de vista")
        ax.plot(d, a["los_m"] - a["f1_m"], "--", color=AZUL, lw=1, label="1.ª zona de Fresnel")
        ax.plot(d, a["los_m"] + a["f1_m"], "--", color=AZUL, lw=1)
        ax.plot(d, a["los_m"] - frac * a["f1_m"], ":", color=NARANJA, lw=1.2, label=f"{frac:.1f} F1 exigido")
        ax.plot([0, 0], [h[0], h[0] + alturas["hA_m"]], color="k", lw=3)
        ax.plot([d[-1], d[-1]], [h[-1], h[-1] + alturas["hB_m"]], color="k", lw=3)
        i = int(np.argmin(a["despeje_rel"][1:-1])) + 1
        ax.annotate(f"punto crítico\n{d[i]:.1f} km, h/F1 = {a['despeje_rel'][i]:.2f}", (d[i], base[i] + cl[i]),
                    xytext=(0, 30), textcoords="offset points", ha="center", fontsize=7,
                    arrowprops=dict(arrowstyle="->", lw=0.7))
        ax.set_ylim(h.min() - 20, max(a["los_m"].max() + a["f1_m"].max(), (base + cl).max()) + 15)
        ax.set_ylabel("Altura (m s. n. m.)")
        ax.set_title(f"k = {k:.2f}: criterio h >= {frac:.1f} F1 (f = {f_GHz} GHz, hA = {alturas['hA_m']:.0f} m, "
                     f"hB = {alturas['hB_m']:.0f} m)", fontsize=9)
    axs[0].legend(fontsize=7, loc="upper left", ncol=3)
    axs[1].set_xlabel("Distancia desde A (km)")
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def despeje(perf: dict, alturas: dict, f_GHz: float, criterios, ruta: Path) -> Path:
    d = perf["d_km"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    for (k, frac), c in zip(criterios, (AZUL, NARANJA)):
        a = prop.analizar_despeje(d, perf["h_m"], perf["clutter_m"], alturas["hA_m"], alturas["hB_m"], f_GHz, k)
        rel = np.clip(a["despeje_rel"][1:-1], -2, 8)
        ax.plot(d[1:-1], rel, color=c, lw=1.2, label=f"h/F1 con k = {k:.2f}")
        ax.axhline(frac, color=c, ls="--", lw=0.9, label=f"mínimo exigido {frac:.1f} (k = {k:.2f})")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylim(-0.5, 8)
    ax.set_xlabel("Distancia desde A (km)")
    ax.set_ylabel("Despeje normalizado h/F1")
    ax.set_title("Despeje de la 1.ª zona de Fresnel a lo largo del trayecto")
    ax.legend(fontsize=7, ncol=2)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def cascada(pres: dict, ruta: Path) -> Path:
    """Diagrama de niveles: potencia acumulada tras cada elemento del enlace."""
    ref = pres["ref"]
    pasos = [("Ptx", ref["ptx_dBm"]), ("Acople Tx", -pres["Lt_dB"]), ("Antena Tx", pres["G_dBi"]),
             ("Espacio libre", -pres["FSPL_dB"]), ("Gases", -pres["A_gases_dB"]), ("Antena Rx", pres["G_dBi"]),
             ("Acople Rx", -pres["Lr_dB"]), ("Desalin./radomo", -pres["Lvarias_dB"])]
    niveles = np.cumsum([v for _, v in pasos])
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(pasos))
    ax.step(np.r_[x, len(pasos)], np.r_[niveles, niveles[-1]], where="post", color=AZUL, lw=1.8)
    ax.plot(x + 0.5, niveles, "o", color=AZUL, ms=4)
    for xi, (nombre, v), nv in zip(x, pasos, niveles):
        ax.annotate(f"{v:+.1f} dB\n→ {nv:.1f} dBm" if xi else f"{nv:.1f} dBm", (xi + 0.5, nv), xytext=(0, 8 if v >= 0 else -22),
                    textcoords="offset points", ha="center", fontsize=6.5, color=VERDE if v >= 0 else ROJO)
    ax.axhline(ref["umbral_dBm"], color=NARANJA, ls="--", lw=1, label=f"Umbral {ref['mod']} = {ref['umbral_dBm']:.1f} dBm")
    ax.fill_between([0, len(pasos)], ref["umbral_dBm"], niveles[-1], color=VERDE, alpha=0.12,
                    label=f"Margen = {ref['margen_dB']:.1f} dB")
    ax.set_xticks(x + 0.5, [p[0] for p in pasos], rotation=20, fontsize=7)
    ax.set_xlim(0, len(pasos))
    ax.set_ylim(min(niveles.min(), ref["umbral_dBm"]) - 32, niveles.max() + 25)
    ax.set_ylabel("Nivel de potencia (dBm)")
    ax.set_title(f"Diagrama de niveles del enlace ({ref['mod']}): Prx = {ref['prx_dBm']:.1f} dBm")
    ax.legend(fontsize=7, loc="upper right")
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def lluvia(disenos: list[dict], ruta: Path) -> Path:
    p = np.logspace(-3, 0, 200)
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for dsg, c in zip(disenos, (ROJO, AZUL, VERDE, NARANJA)):
        A001 = dsg["disponibilidad"]["lluvia"]["A001_dB"]
        a = [itur.atenuacion_lluvia_p(A001, x, dsg["f_GHz"]) for x in p]
        ax.semilogx(p, a, color=c, lw=1.3, label=f"{dsg['id']}: {dsg['banda']}, pol. {dsg['pol']}")
        ax.axhline(dsg["disponibilidad"]["ref"]["margen_efectivo_dB"], color=c, ls=":", lw=1,
                   label=f"margen efectivo {dsg['id']} = {dsg['disponibilidad']['ref']['margen_efectivo_dB']:.1f} dB")
    ax.axvline(0.01, color="k", ls="--", lw=0.8, label="objetivo 0,01 % (99,99 %)")
    ax.set_xlabel("Porcentaje del año excedido p (%)")
    ax.set_ylabel("Atenuación por lluvia (dB)")
    ax.set_title("Atenuación por lluvia excedida (ITU-R P.530-18 / P.838-3)")
    ax.legend(fontsize=6.5)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def acm(diseno: dict, cap_req: float, disp_obj: float, ruta: Path) -> Path:
    curva = [c for c in diseno["disponibilidad"]["curva_acm"] if c["disponibilidad_pct"] > 0]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = [100 - c["disponibilidad_pct"] for c in curva]
    y = [c["capacidad_Mbps"] for c in curva]
    ax.semilogx(x, y, "o-", color=AZUL)
    for c, xi, yi in zip(curva, x, y):
        ax.annotate(c["mod"], (xi, yi), xytext=(4, 3), textcoords="offset points", fontsize=7)
    ax.axhline(cap_req, color=ROJO, ls="--", lw=1, label=f"capacidad mínima {cap_req:.0f} Mbps")
    ax.axvline(100 - disp_obj, color=NARANJA, ls="--", lw=1, label="indisponibilidad máx. 0,01 %")
    ax.set_xlabel("Tiempo anual con la capacidad por debajo del valor indicado (%)")
    ax.set_ylabel("Capacidad (Mbps)")
    ax.set_title(f"Capacidad frente a disponibilidad con modulación adaptativa ({diseno['id']})")
    ax.legend(fontsize=7)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def alternativas(evaluados: list[dict], final: dict, inicial: dict, disp_obj: float, ruta: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    bandas = sorted({e["banda"] for e in evaluados}, key=lambda b: float(b.split()[0]))
    cmap = plt.cm.viridis(np.linspace(0, 0.9, len(bandas)))
    for b, c in zip(bandas, cmap):
        es = [e for e in evaluados if e["banda"] == b and "disponibilidad" in e]
        x = [e["costo"] for e in es]
        y = [max(100 - e["disponibilidad"]["ref"]["disponibilidad_pct"], 1e-5) for e in es]
        ax.scatter(x, y, color=c, s=[22 if e["cumple"] else 10 for e in es],
                   marker="o", label=b, edgecolors=["k" if e["cumple"] else "none" for e in es])
    ax.axhline(100 - disp_obj, color=ROJO, ls="--", lw=1, label="límite 0,01 %")
    for e, t in ((inicial, "inicial"), (final, "seleccionado")):
        ax.annotate(f"{e['id']} ({t})", (e["costo"], max(100 - e["disponibilidad"]["ref"]["disponibilidad_pct"], 1e-5)),
                    xytext=(10, 10), textcoords="offset points", fontsize=7, arrowprops=dict(arrowstyle="->", lw=0.7))
    ax.set_yscale("log")
    ax.set_xlabel("Costo relativo (1,0 = par de radios)")
    ax.set_ylabel("Indisponibilidad anual (%)")
    ax.set_title("Espacio de alternativas evaluadas (borde negro = cumple)")
    ax.legend(fontsize=6.5, ncol=4, loc="upper right")
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def interferencia(diseno: dict, ruta: Path) -> Path:
    G = diseno["presupuesto"]["G_dBi"]
    phi = np.linspace(0, 90, 600)
    g = [ganancia_fuera_eje_dBi(G, diseno["antena_m"], diseno["f_GHz"], x) for x in phi]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(phi, g, color=AZUL, label=f"Diagrama ITU-R F.699, antena {diseno['antena_m']} m, {diseno['f_GHz']} GHz")
    for i, esc in enumerate(diseno["interferencia"]["escenarios"], start=1):
        a = esc["angulo_victima_deg"]
        ax.plot(a, esc["G_fuera_eje_dBi"], "o", color=ROJO)
        ax.annotate(f"E{i}: {esc['G_fuera_eje_dBi']:.1f} dBi", (a, esc["G_fuera_eje_dBi"]), xytext=(6, 6),
                    textcoords="offset points", fontsize=7)
    ax.set_xlabel("Ángulo fuera del eje (°)")
    ax.set_ylabel("Ganancia (dBi)")
    ax.set_title("Discriminación angular de la antena receptora")
    ax.legend(fontsize=7)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def arquitectura(subagentes: list[tuple[str, str]], ruta: Path) -> Path:
    """Diagrama de la arquitectura: orquestador, pizarra y subagentes."""
    from matplotlib.patches import FancyBboxPatch

    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    def caja(x, y, w, h, texto, color, fs=7.5, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.12", fc=color, ec="k", lw=0.8))
        ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center", fontsize=fs, weight="bold" if bold else "normal",
                wrap=True)

    caja(3.3, 5.3, 3.4, 0.8, "Agente ORQUESTADOR\n(motor de reglas o LLM Claude)", "#cfe2f3", 8, True)
    caja(3.3, 3.75, 3.4, 0.85, "PIZARRA compartida\ndatos + unidades + fuente + autor\nmensajes · verificaciones", "#fff2cc", 7)
    ax.annotate("", (5, 4.6), (5, 5.3), arrowprops=dict(arrowstyle="<->", lw=1))
    n = len(subagentes)
    w = 10 / n
    for i, (nombre, desc) in enumerate(subagentes):
        x = i * w + 0.05
        color = "#f4cccc" if nombre == "revisor" else ("#d9ead3" if nombre != "informe" else "#d0e0e3")
        caja(x, 1.3, w - 0.12, 1.55, f"{nombre}\n\n{desc}", color, 6.2)
        ax.annotate("", (x + (w - 0.12) / 2, 2.85), (5, 3.75), arrowprops=dict(arrowstyle="<->", lw=0.6, color=GRIS))
    caja(0.4, 0.1, 4.3, 0.75, "Herramientas: DEM SRTM, geo, propagación,\nITU-R P.530/P.838/P.676/F.699, catálogo", "#eeeeee", 6.5)
    caja(5.3, 0.1, 4.3, 0.75, "Salidas: informe PDF, figuras,\nresultados.json, traza de mensajes", "#eeeeee", 6.5)
    ax.set_title("Arquitectura del sistema multiagente", fontsize=10)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta
