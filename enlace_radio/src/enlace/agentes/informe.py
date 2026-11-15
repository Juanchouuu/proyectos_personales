"""Subagente de informe: genera las figuras y compone el PDF técnico a partir de la pizarra."""
from __future__ import annotations

import datetime as dt
import json

import numpy as np

from ..herramientas import graficas as gr
from ..herramientas.pdf import Constructor
from .base import Agente, Pizarra, Resultado
from .redaccion import hechos, n, redactar_plantilla

DESC_CORTA = {
    "sitios": "coordenadas, DEM,\ndistancia, azimuts",
    "terreno": "perfil, LOS,\nFresnel, alturas",
    "frecuencia_equipos": "banda, canal,\nradio, antenas",
    "presupuesto": "PIRE, pérdidas,\nPrx, margen, ACM",
    "interferencias": "I/N, C/I,\nplan de frec.",
    "disponibilidad": "lluvia P.530,\nmultitrayecto",
    "alternativas": "variantes y\ncostos",
    "revisor": "verificación\nindependiente",
    "informe": "figuras\ny PDF",
}


class AgenteInforme(Agente):
    nombre = "informe"
    rol = "Genera las gráficas y compone automáticamente el informe técnico PDF a partir de la pizarra."
    herramientas = ["graficas.*", "pdf.Constructor", "redaccion.redactar_plantilla / LLM"]

    def ejecutar(self, pz: Pizarra, orquestador=None, textos: dict | None = None, **_) -> Resultado:
        ctx = self.ctx
        fig = ctx.salida / "figuras"
        req = ctx.config["requisitos"]
        A, B = pz.leer("sitio_A"), pz.leer("sitio_B")
        fin, ini = pz.leer("diseno_final"), pz.leer("diseno_inicial")
        ev = pz.leer("evaluados")
        perf = pz.leer("perfil")
        h = hechos(pz, ctx)
        t = redactar_plantilla(h)
        motor = "reglas (determinista)"
        if textos:  # redacción alternativa ya validada (motor LLM)
            t.update(textos)
            motor = "LLM Claude + verificación numérica"
        if orquestador is not None and getattr(orquestador, "motor", None):
            motor = orquestador.motor

        # ---- figuras ----------------------------------------------------------------------
        crit = fin["alturas"]["criterios"]
        figs = {}
        try:
            figs["mapa"] = gr.mapa(ctx.dem, A, B, fig / "mapa.png")
        except Exception as e:  # sin DEM local
            pz.mensaje(self.nombre, "orquestador", "alerta", f"mapa no disponible: {e}")
        figs["perfil"] = gr.perfil(perf, fin["alturas"], fin["f_GHz"], crit, fig / "perfil.png")
        figs["despeje"] = gr.despeje(perf, fin["alturas"], fin["f_GHz"], crit, fig / "despeje.png")
        figs["cascada"] = gr.cascada(fin["presupuesto"], fig / "presupuesto.png")
        figs["lluvia"] = gr.lluvia([ini, fin], fig / "lluvia.png")
        figs["acm"] = gr.acm(fin, req["capacidad_minima_mbps"], req["disponibilidad_objetivo_pct"], fig / "acm.png")
        figs["alternativas"] = gr.alternativas(ev, fin, ini, req["disponibilidad_objetivo_pct"], fig / "alternativas.png")
        figs["interferencia"] = gr.interferencia(fin, fig / "interferencia.png")
        subag = [(nm, DESC_CORTA.get(nm, "")) for nm in (orquestador.agentes if orquestador else DESC_CORTA)]
        figs["arquitectura"] = gr.arquitectura(subag, fig / "arquitectura.png")

        # ---- documento --------------------------------------------------------------------
        ruta = ctx.salida / "informe_enlace_radio.pdf"
        doc = Constructor(ruta, ctx.config["proyecto"])
        cumple = fin["cumple"]
        doc.portada(
            "Diseño y validación de un enlace de radio punto a punto",
            ctx.config["proyecto"],
            [f"Requisitos: ~{n(req['distancia_objetivo_km'], 0)} km · ≥ {n(req['capacidad_minima_mbps'], 0)} Mbps · "
             f"disponibilidad ≥ {n(req['disponibilidad_objetivo_pct'], 2)} %",
             f"Motor de agentes: {motor}",
             "Informe generado automáticamente el " + dt.datetime.now().strftime("%d/%m/%Y a las %H:%M")],
            f"<b>Veredicto: {'CUMPLE' if cumple else 'NO CUMPLE'}</b><br/>Diseño seleccionado {fin['id']}: "
            f"{fin['descripcion']}<br/>Capacidad garantizada {n(h['cap_ref'], 0)} Mbps ({h['mod_ref']}) · "
            f"disponibilidad {n(h['disp'], 4)} % · alturas {n(h['hA'], 0)} m / {n(h['hB'], 0)} m", cumple)

        # 1. Resumen
        doc.seccion("Resumen ejecutivo")
        doc.p(t["resumen"])
        filas = [["Parámetro", "Requisito", "Resultado", "Estado"],
                 ["Distancia", f"~{n(req['distancia_objetivo_km'], 0)} km", f"{n(h['distancia_km'], 2)} km", "OK"],
                 ["Capacidad garantizada", f"≥ {n(req['capacidad_minima_mbps'], 0)} Mbps",
                  f"{n(h['cap_ref'], 0)} Mbps ({h['mod_ref']})", "OK" if h["cap_ref"] >= h["cap_req"] else "NO"],
                 ["Disponibilidad anual", f"≥ {n(req['disponibilidad_objetivo_pct'], 2)} %", f"{n(h['disp'], 4)} %",
                  "OK" if h["disp"] >= h["disp_req"] else "NO"],
                 ["Despeje k = 4/3", "≥ 1,0 F1", f"{n(h['despeje_k43'], 2)} F1", "OK"],
                 ["Despeje k = 2/3", "≥ 0,3 F1", f"{n(h['despeje_k23'], 2)} F1", "OK"],
                 ["Degradación por interferencia", "≤ 1 dB (I/N ≤ -6 dB)", f"{n(h['td'], 2)} dB",
                  "OK" if fin["interferencia"]["cumple"] else "NO"]]
        doc.tabla(filas, "Cumplimiento de requisitos del diseño seleccionado.", [4.5, 3.8, 4.8, 2],
                  {i: ("verde" if filas[i][3] == "OK" else "rojo") for i in range(1, len(filas))})

        # 2. Sistema multiagente
        doc.seccion("Sistema multiagente que produjo este informe")
        doc.p("Este informe lo generó, sin edición manual, un sistema compuesto por un <b>agente orquestador</b> y "
              "subagentes especializados que se comunican a través de una <b>pizarra compartida</b>. Cada dato de la "
              "pizarra registra su valor, unidades, fuente y agente autor. Los cálculos los hacen herramientas de "
              "código verificables (no se estiman a mano), y un <b>agente revisor</b> recalcula los resultados críticos "
              "con fórmulas independientes antes de autorizar el informe. El Anexo A muestra la traza completa de "
              "mensajes entre agentes de esta ejecución.")
        doc.figura(figs["arquitectura"], "Arquitectura: orquestador, pizarra, subagentes y herramientas.", 15.5)
        filas = [["Agente", "Responsabilidad", "Herramientas"]]
        if orquestador is not None:
            filas.append(["orquestador", orquestador.rol, "delegación, decisión, criterio de costo mínimo"])
            for a in orquestador.agentes.values():
                filas.append([a.nombre, a.rol, ", ".join(a.herramientas)])
        doc.tabla(filas, "Responsabilidades de los agentes.", [2.8, 8.6, 5.2])

        # 3. Sitios
        doc.seccion("Emplazamientos seleccionados")
        filas = [["", "Sitio A (central)", "Sitio B (sede rural)"],
                 ["Nombre", A["nombre"], B["nombre"]],
                 ["Latitud (WGS84)", f"{A['lat']:.4f}° ({A['lat_dms']})", f"{B['lat']:.4f}° ({B['lat_dms']})"],
                 ["Longitud (WGS84)", f"{A['lon']:.4f}° ({A['lon_dms']})", f"{B['lon']:.4f}° ({B['lon_dms']})"],
                 ["Elevación del terreno", f"{n(A['elev_m'])} m s. n. m.", f"{n(B['elev_m'])} m s. n. m."],
                 ["Soporte de antena", A["tipo_soporte"], B["tipo_soporte"]],
                 ["Altura de antena (diseño)", f"{n(h['hA'], 0)} m sobre el suelo", f"{n(h['hB'], 0)} m sobre el suelo"],
                 ["Azimut de apuntamiento", f"{n(h['azimut_AB'], 2)}°", f"{n(h['azimut_BA'], 2)}°"]]
        doc.tabla(filas, f"Coordenadas y datos de los sitios. Distancia: {n(h['distancia_km'], 3)} km.", [3.6, 6.5, 6.5],
                  fuente="coordenadas WGS84; elevación SRTM 1\" interpolada")
        doc.sub("Justificación de la ubicación")
        doc.p(f"<b>Sitio A.</b> {A['justificacion']}")
        doc.p(f"<b>Sitio B.</b> {B['justificacion']}")
        if "mapa" in figs:
            doc.figura(figs["mapa"], "Mapa topográfico (SRTM 1\", sombreado e isohipsas cada 200 m) con los sitios, "
                       "el trayecto y las poblaciones cercanas.", 13.5)

        # 4. Terreno
        doc.seccion("Perfil del terreno, línea de vista y zona de Fresnel")
        doc.p(f"El perfil se extrajo del DEM SRTM 1\" con {len(perf['d_km'])} muestras (una cada "
              f"{ctx.config['dem']['paso_muestreo_m']:.0f} m) a lo largo del círculo máximo A-B. Sobre el terreno se "
              "sumaron el abultamiento de la Tierra equivalente, h = d1·d2/(12,74·k), y una capa de clutter. El "
              "radio de la primera zona de Fresnel es r1 = 17,32·√(d1·d2/(f·d)). Para fijar las alturas de antena se usan "
              "los dos criterios de ITU-R P.530: despeje de 1,0 F1 con k = 4/3 (refracción mediana) y de 0,3 F1 con "
              "k = 2/3 (subrefracción, obstáculo extendido). El agente de terreno busca el par de alturas de menor suma "
              "que cumple ambos.")
        doc.p(t["terreno"])
        doc.figura(figs["perfil"], "Perfil del trayecto con línea de vista, 1.ª zona de Fresnel y despeje exigido "
                   "para k = 4/3 (arriba) y k = 2/3 (abajo).")
        doc.figura(figs["despeje"], "Despeje normalizado h/F1 a lo largo del trayecto.")
        det = fin["alturas"]["detalle"]
        filas = [["Condición", "k", "Exigido", "h/F1 mínimo", "Punto crítico", "Despeje", "F1 en el punto"]]
        for nm, dd in det.items():
            filas.append([nm.replace("_", " "), n(dd["k"], 2), f"{n(dd['fraccion_exigida'], 1)} F1",
                          n(dd["despeje_rel_min"], 2), f"{n(dd['d_critico_km'], 2)} km", f"{n(dd['despeje_min_m'], 1)} m",
                          f"{n(dd['f1_critico_m'], 1)} m"])
        doc.tabla(filas, f"Verificación de despeje a {n(fin['f_GHz'])} GHz con hA = {n(h['hA'], 0)} m y hB = {n(h['hB'], 0)} m.",
                  [2.6, 1.2, 1.8, 2.2, 2.5, 2.2, 2.6])
        alt_f = pz.leer("alturas_cache")
        filas = [["Frecuencia (GHz)", "hA mín. (m)", "hB mín. (m)", "h/F1 (k=4/3)", "h/F1 (k=2/3)"]]
        for f_, r_ in sorted(alt_f.items()):
            if r_:
                filas.append([n(f_), n(r_["hA_m"], 0), n(r_["hB_m"], 0), n(r_["detalle"]["k_mediano"]["despeje_rel_min"], 2),
                              n(r_["detalle"]["k_minimo"]["despeje_rel_min"], 2)])
        doc.tabla(filas, "Alturas mínimas de antena por banda calculadas por el agente de terreno.", [3.2, 2.6, 2.6, 3, 3])

        # 5. Frecuencia y equipos
        doc.seccion("Frecuencia de operación y equipos")
        doc.p(t["frecuencia"])
        b = ctx.catalogo.banda(fin["banda"])
        ant = ctx.catalogo.antena(fin["antena_m"])
        pres = fin["presupuesto"]
        filas = [["Elemento", "Especificación"],
                 ["Banda / canalización", f"{b['banda']} ({b['rango']}), {b['rec_canalizacion']}, canal de {fin['ancho_MHz']} MHz"],
                 ["Frecuencia de cálculo", f"{n(fin['f_GHz'])} GHz, polarización {fin['pol']}"],
                 ["Radio", ctx.catalogo.radio["modelo"]],
                 ["Modulación", f"ACM QPSK…2048QAM; garantizada {h['mod_ref']}, máxima en cielo despejado {h['mod_max']}"],
                 ["Potencia de transmisión", f"{n(pres['ref']['ptx_dBm'])} dBm en {h['mod_ref']}"],
                 ["Umbral de recepción", f"{n(pres['ref']['umbral_dBm'])} dBm (BER 10⁻⁶) en {h['mod_ref']}"],
                 ["Figura de ruido", f"{n(ctx.catalogo.radio['figura_ruido_dB'])} dB"],
                 ["Antenas", f"Parabólicas de {n(fin['antena_m'])} m, eficiencia {n(ant['eficiencia'], 2)}, ganancia "
                             f"{n(pres['G_dBi'])} dBi, ancho de haz {n(pres['ancho_haz_deg'], 2)}°, F/B {ant['relacion_FB_dB']} dB, "
                             f"XPD {ant['XPD_dB']} dB"],
                 ["Instalación", f"A: {A['tipo_soporte']} ({n(h['hA'], 0)} m); B: {B['tipo_soporte']} ({n(h['hB'], 0)} m)"]]
        doc.tabla(filas, "Equipos del diseño seleccionado.", [4, 12.6], fuente="catálogo data/equipos.json (perfiles típicos)")
        filas = [["Modulación", "Capacidad (Mbps)", "Ptx (dBm)", "Umbral (dBm)", "Prx (dBm)", "Margen (dB)", "Disponib. (%)"]]
        res = {}
        for i, (fila, c) in enumerate(zip(pres["tabla"], fin["disponibilidad"]["curva_acm"]), start=1):
            filas.append([fila["mod"], n(fila["capacidad_Mbps"], 0), n(fila["ptx_dBm"]), n(fila["umbral_dBm"]),
                          n(fila["prx_dBm"]), n(fila["margen_dB"]), n(c["disponibilidad_pct"], 4) if c["disponibilidad_pct"] > 0 else "-"])
            if fila["mod"] == h["mod_ref"]:
                res[i] = "verde"
        doc.tabla(filas, "Tabla ACM del diseño: capacidad, presupuesto y disponibilidad por modulación (en verde, la "
                  "modulación que garantiza la capacidad mínima).", [2.4, 2.5, 2.0, 2.3, 2.2, 2.2, 2.6], res)

        # 6. Presupuesto
        doc.seccion("Cálculos y presupuesto del enlace")
        doc.p("Ecuación del enlace: Prx = Ptx − Lt + Gt − FSPL − Agases + Gr − Lr − Lvarias, con FSPL = 92,45 + "
              "20·log10(f[GHz]) + 20·log10(d[km]) (ITU-R P.525). La atenuación por gases sigue la aproximación de ITU-R "
              "P.676, con corrección de presión por la altitud media del trayecto.")
        doc.p(t["presupuesto"])
        filas = [["Término", "Valor", "Unidad", "Fuente / supuesto"],
                 ["Potencia de transmisión (Ptx)", n(pres["ref"]["ptx_dBm"]), "dBm", f"catálogo, {h['mod_ref']}"],
                 ["Pérdidas de acople Tx (Lt)", n(pres["Lt_dB"]), "dB", "radio full-outdoor"],
                 ["Ganancia antena Tx (Gt)", n(pres["G_dBi"], 2), "dBi", "G = 10·log10(η(πD/λ)²)"],
                 ["PIRE", n(pres["ref"]["pire_dBm"], 2), "dBm", "Ptx − Lt + Gt"],
                 ["Pérdida en espacio libre", n(pres["FSPL_dB"], 2), "dB", "ITU-R P.525"],
                 ["Atenuación por gases", n(pres["A_gases_dB"], 3), "dB",
                  f"P.676: γo = {n(pres['gamma_o_dB_km'], 4)}, γw = {n(pres['gamma_w_dB_km'], 4)} dB/km"],
                 ["Ganancia antena Rx (Gr)", n(pres["G_dBi"], 2), "dBi", "idéntica a Tx"],
                 ["Pérdidas de acople Rx (Lr)", n(pres["Lr_dB"]), "dB", "radio full-outdoor"],
                 ["Desalineación y radomos", n(pres["Lvarias_dB"]), "dB", "supuesto"],
                 ["Potencia recibida (Prx)", n(pres["ref"]["prx_dBm"], 2), "dBm", "resultado"],
                 ["Umbral del receptor", n(pres["ref"]["umbral_dBm"]), "dBm", f"BER 10⁻⁶, {h['mod_ref']}"],
                 ["Margen de desvanecimiento", n(pres["ref"]["margen_dB"], 2), "dB", "Prx − umbral"],
                 ["Degradación por interferencia", n(h["td"], 2), "dB", "agente de interferencias"],
                 ["Margen efectivo", n(h["margen_ef"], 2), "dB", "usado para la disponibilidad"]]
        doc.tabla(filas, "Presupuesto de potencia del diseño seleccionado.", [5.2, 2.2, 1.6, 7.6], {10: "verde", 14: "verde"})
        doc.figura(figs["cascada"], "Diagrama de niveles (cascada) del presupuesto de potencia.")

        # 7. Interferencias
        doc.seccion("Análisis de interferencias y plan de frecuencias")
        doc.p("Para cada escenario se calcula la potencia interferente I = Ptx,i + Gi(φi) − FSPL + Gv(φv) − Lr − XPD/NFD, "
              "con diagramas de radiación de referencia de ITU-R F.699 en ambas antenas, y se compara con el ruido "
              "térmico N = −174 + 10·log10(B) + NF. El criterio de largo plazo es I/N ≤ −6 dB (ITU-R F.758), que equivale "
              "a una degradación del umbral de 1 dB como máximo. Si un escenario cocanal no cumple, el agente aplica primero "
              "polarización cruzada y luego canal adyacente.")
        doc.p(t["interferencias"])
        filas = [["Escenario", "d (km)", "I/N cocanal (dB)", "Mitigación", "I (dBm)", "I/N (dB)", "C/I (dB)", "Degrad. (dB)"]]
        rs = {}
        for i, e in enumerate(fin["interferencia"]["escenarios"], start=1):
            filas.append([f"E{i}: {e['nombre']}", n(e["distancia_km"]), n(e["cocanal_I_N_dB"]), e["mitigacion"], n(e["I_dBm"]),
                          n(e["I_N_dB"]), n(e["C_I_dB"]), n(e["degradacion_umbral_dB"], 2)])
            rs[i] = "verde" if e["cumple"] else "rojo"
        doc.tabla(filas, "Escenarios de interferencia evaluados.", [4.4, 1.2, 1.9, 3.2, 1.5, 1.4, 1.4, 1.6], rs,
                  fuente=ctx.config["interferencia"]["fuente"])
        doc.figura(figs["interferencia"], "Diagrama de referencia F.699 de la antena receptora y ganancia en la "
                   "dirección de cada interferente.")

        # 8. Disponibilidad
        doc.seccion("Evaluación de capacidad y disponibilidad")
        lluv = fin["disponibilidad"]["lluvia"]
        doc.p("La atenuación por lluvia se calcula con ITU-R P.530-18 §2.4.1: A0,01 = γR·r·d, con γR = k·R0,01^α "
              "(coeficientes de ITU-R P.838-3) y el factor de distancia r. Para otros porcentajes se escala con "
              "Ap = A0,01·C1·p^−(C2 + C3·log10 p), y se busca numéricamente el porcentaje en que la lluvia supera el "
              "margen. El multitrayecto se calcula con el método rápido de P.530-18 §2.3.1.")
        doc.p(t["disponibilidad"])
        mp = fin["disponibilidad"]["ref"]["multitrayecto"]
        filas = [["Parámetro", "Valor", "Parámetro", "Valor"],
                 ["R0,01", f"{n(ctx.config['clima']['R001_mm_h'], 0)} mm/h", "k / α (P.838-3)", f"{lluv['k']:.5f} / {lluv['alfa']:.4f}"],
                 ["γR", f"{n(lluv['gamma_dB_km'], 4)} dB/km", "r (factor de distancia)", n(lluv["r"], 4)],
                 ["d efectiva", f"{n(lluv['d_eff_km'], 2)} km", "A0,01", f"{n(lluv['A001_dB'], 2)} dB"],
                 ["Margen efectivo", f"{n(h['margen_ef'], 2)} dB", "Indisponibilidad por lluvia", f"{n(h['p_lluvia'], 6)} %"],
                 ["dN1", n(ctx.config["clima"]["dN1"], 0), "K (multitrayecto)", f"{mp['K']:.3e}"],
                 ["|εp|", f"{n(mp['eps_p_mrad'], 2)} mrad", "p0 (factor de ocurrencia)", f"{n(mp['p0_pct'], 4)} %"],
                 ["Multitrayecto (mes peor)", f"{h['p_multi']:.2e} %", "Indisponibilidad total", f"{n(h['p_total'], 6)} %"],
                 ["Disponibilidad", f"{n(h['disp'], 5)} %", "Tiempo fuera de servicio", f"{n(h['p_total'] / 100 * 525960, 1)} min/año"]]
        doc.tabla(filas, "Cálculo de disponibilidad del diseño seleccionado.", [3.6, 4.6, 4.2, 4.2], {8: "verde"})
        doc.figura(figs["lluvia"], "Atenuación por lluvia excedida frente al porcentaje del año, para el diseño inicial y "
                   "el seleccionado, con sus márgenes efectivos.")
        doc.figura(figs["acm"], "Capacidad disponible frente a disponibilidad con modulación adaptativa (ACM).")

        # 9. Alternativas
        doc.seccion("Diseño inicial y alternativas evaluadas")
        doc.p(f"Diseño inicial {ini['id']}: {ini['descripcion']}. Resultado: "
              f"{'cumple' if ini['cumple'] else 'NO cumple'}"
              + (f" ({ini.get('motivos') and '; '.join(ini['motivos'])})." if not ini["cumple"] else ".")
              + f" Cuando el diseño no cumple, el agente de alternativas genera variantes combinando las bandas licenciadas "
              f"del catálogo, los anchos de canal, los diámetros de antena (0,6 a 1,8 m) y la polarización. El orquestador "
              f"las evalúa todas con la misma cadena de subagentes y escoge la de <b>menor costo relativo</b> que cumple "
              f"(en caso de empate, la de mayor margen). En total se evaluaron {h['n_eval']} diseños y {h['n_cumplen']} cumplen.")
        doc.figura(figs["alternativas"], "Costo relativo frente a indisponibilidad de todas las variantes evaluadas.")
        orden = sorted([e for e in ev if "disponibilidad" in e],
                       key=lambda e: (not e["cumple"], e["costo"], -e["disponibilidad"]["ref"]["disponibilidad_pct"]))
        filas = [["ID", "Variante", "Modulación", "Margen ef. (dB)", "A0,01 (dB)", "Disponib. (%)", "Costo", "Cumple"]]
        rs = {}
        mostrar = orden[:14] + [e for e in orden[14:] if e["id"] == ini["id"]]
        for i, e in enumerate(mostrar, start=1):
            filas.append([e["id"], e["descripcion"], e["presupuesto"]["ref"]["mod"],
                          n(e["disponibilidad"]["ref"]["margen_efectivo_dB"]), n(e["disponibilidad"]["lluvia"]["A001_dB"]),
                          n(e["disponibilidad"]["ref"]["disponibilidad_pct"], 4), n(e["costo"], 2), "Sí" if e["cumple"] else "No"])
            if e["id"] == fin["id"]:
                rs[i] = "verde"
            elif e["id"] == ini["id"]:
                rs[i] = "rojo"
        doc.tabla(filas, "Variantes ordenadas por cumplimiento y costo (verde: seleccionada; rojo: diseño inicial).",
                  [1.2, 5.6, 1.7, 1.8, 1.6, 1.9, 1.3, 1.3], rs)
        mejores = {}
        for e in ev:
            if "disponibilidad" in e:
                b_ = e["banda"]
                if b_ not in mejores or e["disponibilidad"]["ref"]["disponibilidad_pct"] > mejores[b_]["disponibilidad"]["ref"]["disponibilidad_pct"]:
                    mejores[b_] = e
        filas = [["Banda", "Mejor variante de la banda", "Disponib. (%)", "¿Cumple?"]]
        for b_, e in sorted(mejores.items(), key=lambda x: float(x[0].split()[0])):
            filas.append([b_, e["descripcion"], n(e["disponibilidad"]["ref"]["disponibilidad_pct"], 4), "Sí" if e["cumple"] else "No"])
        doc.tabla(filas, "Mejor resultado alcanzable en cada banda: muestra por qué las bandas altas se descartan.",
                  [2.2, 8.4, 3, 2.4])
        doc.p("Otras alternativas que se analizaron cualitativamente: (a) un salto con repetidor, que no hace falta porque "
              "hay variantes directas que cumplen; (b) diversidad de espacio o de frecuencia, que no se justifica porque el "
              "multitrayecto es despreciable frente a la lluvia; (c) la banda de 5,8 GHz de uso libre, descartada porque no "
              "tiene protección frente a interferencias y no permite garantizar el 99,99 %.")

        # 10. Revisión
        doc.seccion("Revisión técnica y verificaciones")
        doc.p("Todas las comprobaciones registradas por los agentes durante la ejecución. Las del agente revisor usan fórmulas "
              "independientes (Friis con λ, ley de cosenos esférica, despeje vectorial con radio terrestre explícito, tablas "
              "publicadas de P.838-3) para detectar errores de unidades o de implementación.")
        filas = [["Agente", "Comprobación", "Detalle", "Resultado"]]
        rs = {}
        vistos = set()
        for v in pz.verificaciones:
            clave = (v.agente, v.nombre, v.detalle)
            if clave in vistos:
                continue
            vistos.add(clave)
            filas.append([v.agente, v.nombre, v.detalle, "OK" if v.ok else ("FALLO" if v.critica else "AVISO")])
            rs[len(filas) - 1] = "verde" if v.ok else ("rojo" if v.critica else "amarillo")
        doc.tabla(filas, "Registro de verificaciones.", [2.3, 5.0, 7.3, 2.0], rs)

        # 11. Supuestos y fuentes
        doc.seccion("Supuestos, fuentes y referencias")
        doc.sub("Supuestos")
        doc.vinetas([f"<i>[{a}]</i> {s}" for a, s in pz.supuestos])
        doc.sub("Fuentes de datos")
        doc.vinetas([f"<b>{k}:</b> {v}" for k, v in pz.fuentes.items()] +
                    [f"<b>Clima:</b> {ctx.config['clima']['fuente_R001']}; {ctx.config['clima']['fuente_dN1']}",
                     f"<b>Clutter:</b> {ctx.config['clutter']['fuente']}"])
        doc.sub("Recomendaciones y normas")
        doc.vinetas([
            "ITU-R P.525: Cálculo de la atenuación en el espacio libre.",
            "ITU-R P.526: Propagación por difracción (zonas de Fresnel).",
            "ITU-R P.530-18: Datos de propagación y métodos de predicción para sistemas terrenales con visibilidad directa.",
            "ITU-R P.838-3: Modelo de la atenuación específica debida a la lluvia.",
            "ITU-R P.837: Características de la precipitación para establecer modelos de propagación.",
            "ITU-R P.676: Atenuación debida a los gases atmosféricos.",
            "ITU-R P.453: Índice de refracción radioeléctrica (dN1).",
            "ITU-R F.699: Diagramas de radiación de referencia para antenas de sistemas fijos (1-70 GHz).",
            "ITU-R F.758: Consideraciones sobre criterios de protección contra interferencias en el servicio fijo.",
            "ITU-R F.385 / F.386 / F.387 / F.497 / F.636 / F.595 / F.637: Disposiciones de radiocanales por banda.",
            "ETSI EN 302 217-2 y -4: Radioenlaces fijos punto a punto (equipos y antenas).",
            "NASA/USGS SRTM 1 arc-second Global (DEM), distribuido por AWS Open Data (Terrain Tiles)."])

        # 12. Conclusiones
        doc.seccion("Conclusiones y recomendaciones")
        doc.sub("Conclusiones")
        doc.vinetas(t["conclusiones"])
        doc.sub("Recomendaciones")
        doc.vinetas(t["recomendaciones"])

        # Anexos
        doc.salto()
        doc.anexo("A", "Traza de mensajes entre agentes")
        filas = [["t (s)", "De", "Para", "Tipo", "Contenido"]]
        for m in pz.mensajes:
            filas.append([f"{m.t:.2f}", m.de, m.para, m.tipo, m.contenido])
        doc.tabla(filas, "Mensajes intercambiados durante la ejecución (las evaluaciones de alternativas se resumen en "
                  "una línea por variante).", [1.0, 2.4, 2.5, 2.0, 8.7])
        doc.anexo("B", "Datos de entrada y reproducibilidad")
        doc.p("Todos los datos de entrada están en <b>config/escenario.json</b> (sitios, requisitos, clima, clutter, "
              "interferencias) y <b>data/equipos.json</b> (catálogo). El perfil extraído se guarda en "
              "<b>data/perfil_terreno.csv</b> y los resultados completos en <b>salida/resultados.json</b>. Para "
              "regenerar este informe: <font face='Courier'>python -m enlace</font> (ver README.md).")
        p_ = perf
        filas = [["d (km)", "Lat", "Lon", "Terreno (m)", "Clutter (m)"]]
        for i in np.linspace(0, len(p_["d_km"]) - 1, 29).astype(int):
            filas.append([n(p_["d_km"][i], 2), f"{p_['lat'][i]:.5f}", f"{p_['lon'][i]:.5f}", n(p_["h_m"][i], 1),
                          n(p_["clutter_m"][i], 0)])
        doc.tabla(filas, "Extracto del perfil de terreno (1 de cada ~33 muestras).", [2.5, 3, 3, 3, 3])

        doc.construir()
        self._json(pz, h)
        pz.escribir("ruta_pdf", str(ruta), self.nombre)
        return Resultado(self.nombre, True, f"PDF generado en {ruta} ({ruta.stat().st_size // 1024} kB, "
                         f"{doc.n_fig} figuras, {doc.n_tab} tablas)")

    def _json(self, pz: Pizarra, h: dict) -> None:
        def limpio(x):
            if isinstance(x, dict):
                return {str(k): limpio(v) for k, v in x.items()}
            if isinstance(x, (list, tuple)):
                return [limpio(v) for v in x]
            if isinstance(x, np.ndarray):
                return None
            if isinstance(x, (np.floating, np.integer)):
                return x.item()
            return x
        fin = pz.leer("diseno_final")
        out = {"resumen": h, "diseno_final": limpio(fin), "diseno_inicial": limpio(pz.leer("diseno_inicial")),
               "alternativas": [{k: limpio(e.get(k)) for k in ("id", "descripcion", "cumple", "costo")}
                                | {"disponibilidad_pct": e.get("disponibilidad", {}).get("ref", {}).get("disponibilidad_pct")}
                                for e in pz.leer("evaluados")],
               "verificaciones": [vars(v) for v in pz.verificaciones],
               "supuestos": pz.supuestos, "mensajes": [vars(m) for m in pz.mensajes]}
        (self.ctx.salida / "resultados.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                         encoding="utf-8")
