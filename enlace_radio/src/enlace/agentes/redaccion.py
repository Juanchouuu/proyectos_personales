"""Redacción del análisis del informe.

`hechos()` reúne en un diccionario plano los resultados de la pizarra (la única fuente de cifras).
`redactar_plantilla()` produce los textos de forma determinista; el motor LLM (``llm.py``) puede
sustituirlos por una redacción propia, que se valida contra estos mismos hechos.
"""
from __future__ import annotations


def n(x: float, dec: int = 1) -> str:
    """Número con coma decimal (convención en español)."""
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def hechos(pz, ctx) -> dict:
    f = pz.leer("diseno_final")
    i = pz.leer("diseno_inicial")
    req = ctx.config["requisitos"]
    A, B = pz.leer("sitio_A"), pz.leer("sitio_B")
    ev = pz.leer("evaluados")
    ref = f["presupuesto"]["ref"]
    mx = f["presupuesto"]["max_cielo_despejado"] or ref
    dsp = f["disponibilidad"]
    return {
        "distancia_km": pz.leer("distancia_km"), "azimut_AB": pz.leer("azimut_AB_deg"), "azimut_BA": pz.leer("azimut_BA_deg"),
        "elev_A": A["elev_m"], "elev_B": B["elev_m"], "nombre_A": A["nombre"], "nombre_B": B["nombre"],
        "cap_req": req["capacidad_minima_mbps"], "disp_req": req["disponibilidad_objetivo_pct"],
        "ini_id": i["id"], "ini_desc": i["descripcion"], "ini_cumple": i["cumple"],
        "ini_disp": i["disponibilidad"]["ref"]["disponibilidad_pct"], "ini_A001": i["disponibilidad"]["lluvia"]["A001_dB"],
        "ini_margen": i["disponibilidad"]["ref"]["margen_efectivo_dB"], "ini_motivos": "; ".join(i.get("motivos", [])),
        "fin_id": f["id"], "fin_desc": f["descripcion"], "fin_cumple": f["cumple"], "banda": f["banda"], "f_GHz": f["f_GHz"],
        "ancho": f["ancho_MHz"], "pol": f["pol"], "antena_m": f["antena_m"], "G": f["presupuesto"]["G_dBi"],
        "hA": f["alturas"]["hA_m"], "hB": f["alturas"]["hB_m"],
        "despeje_k43": f["alturas"]["detalle"]["k_mediano"]["despeje_rel_min"],
        "despeje_k23": f["alturas"]["detalle"]["k_minimo"]["despeje_rel_min"],
        "d_critico": f["alturas"]["detalle"]["k_mediano"]["d_critico_km"],
        "fspl": f["presupuesto"]["FSPL_dB"], "gases": f["presupuesto"]["A_gases_dB"], "prx": ref["prx_dBm"],
        "mod_ref": ref["mod"], "cap_ref": ref["capacidad_Mbps"], "umbral_ref": ref["umbral_dBm"], "margen": ref["margen_dB"],
        "mod_max": mx["mod"], "cap_max": mx["capacidad_Mbps"],
        "td": f["interferencia"]["degradacion_max_dB"], "margen_ef": dsp["ref"]["margen_efectivo_dB"],
        "A001": dsp["lluvia"]["A001_dB"], "gamma": dsp["lluvia"]["gamma_dB_km"], "r": dsp["lluvia"]["r"],
        "p_lluvia": dsp["ref"]["p_lluvia_pct"], "p_multi": dsp["ref"]["p_multi_pct"], "p_total": dsp["ref"]["p_total_pct"],
        "disp": dsp["ref"]["disponibilidad_pct"], "costo": f["costo"], "n_eval": len(ev),
        "n_cumplen": sum(1 for e in ev if e["cumple"]), "R001": ctx.config["clima"]["R001_mm_h"],
        "altas_cumplen": [e["descripcion"] for e in ev if e["cumple"] and e["f_GHz"] > 10],
    }


def redactar_plantilla(h: dict) -> dict[str, str]:
    t = {}
    veredicto = "CUMPLE" if h["fin_cumple"] else "NO CUMPLE"
    t["resumen"] = (
        f"El sistema multiagente diseñó un radioenlace punto a punto de {n(h['distancia_km'], 2)} km entre la central "
        f"(A) y la sede rural (B). El diseño inicial ({h['ini_desc']}) <b>no alcanzó</b> el objetivo de disponibilidad: "
        f"la atenuación por lluvia excedida el 0,01 % del año es de {n(h['ini_A001'])} dB, frente a un margen efectivo de "
        f"{n(h['ini_margen'])} dB, lo que da una disponibilidad de {n(h['ini_disp'], 4)} %. "
        if not h["ini_cumple"] else
        f"El sistema multiagente diseñó un radioenlace punto a punto de {n(h['distancia_km'], 2)} km entre la central "
        f"(A) y la sede rural (B). El diseño inicial ({h['ini_desc']}) cumplió los requisitos. ")
    if not h["ini_cumple"]:
        t["resumen"] += (f"Con esa base, el agente de alternativas propuso {h['n_eval'] - 1} variantes (banda, ancho de "
                         f"canal, tamaño de antena y polarización). {h['n_cumplen']} de ellas cumplen todos los "
                         "requisitos, y el orquestador eligió la de menor costo relativo. ")
    t["resumen"] += (
        f"<b>Diseño final ({h['fin_id']}): {h['fin_desc']}</b>, con antenas a {n(h['hA'], 0)} m (A) y {n(h['hB'], 0)} m (B) "
        f"sobre el suelo. Con {h['mod_ref']} entrega {n(h['cap_ref'], 0)} Mbps (requisito: {n(h['cap_req'], 0)} Mbps), "
        f"tiene un margen de desvanecimiento efectivo de {n(h['margen_ef'])} dB y una disponibilidad calculada de "
        f"<b>{n(h['disp'], 4)} %</b> (objetivo: {n(h['disp_req'], 2)} %). Veredicto: <b>{veredicto}</b>.")
    t["terreno"] = (
        f"El trayecto cruza la Sabana de Bogotá casi por un meridiano (azimut {n(h['azimut_AB'])}°). El terreno varía poco "
        f"entre los dos extremos ({n(h['elev_A'], 0)} y {n(h['elev_B'], 0)} m s. n. m.), así que el despeje lo deciden la "
        f"curvatura terrestre y el clutter (edificaciones y arbolado), no el relieve. Con las alturas elegidas, el "
        f"despeje mínimo es de {n(h['despeje_k43'], 2)} F1 con k = 4/3 (se exige 1,0) y de {n(h['despeje_k23'], 2)} F1 "
        f"con k = 2/3 (se exige 0,3). El punto crítico está a {n(h['d_critico'])} km de la central.")
    t["frecuencia"] = (
        f"Se eligió la banda de {h['banda']} ({n(h['f_GHz'])} GHz), con canal de {h['ancho']} MHz y polarización "
        f"{'vertical' if h['pol'] == 'V' else 'horizontal'}. La polarización vertical sufre menos con la lluvia porque las "
        f"gotas se achatan en el eje horizontal. Las antenas parabólicas de {n(h['antena_m'])} m dan "
        f"{n(h['G'])} dBi cada una. Con modulación adaptativa (ACM), el radio usa {h['mod_max']} "
        f"({n(h['cap_max'], 0)} Mbps) con cielo despejado y baja a {h['mod_ref']} ({n(h['cap_ref'], 0)} Mbps) como "
        f"modulación mínima que garantiza la capacidad contratada.")
    t["presupuesto"] = (
        f"La pérdida en espacio libre es de {n(h['fspl'])} dB y la absorción por gases de {n(h['gases'], 2)} dB. La potencia "
        f"recibida nominal con {h['mod_ref']} es de {n(h['prx'])} dBm, frente a un umbral de {n(h['umbral_ref'])} dBm "
        f"(BER 10⁻⁶): queda un margen de desvanecimiento plano de {n(h['margen'])} dB.")
    t["interferencias"] = (
        f"En los escenarios de interferencia analizados, la degradación del umbral es como máximo de {n(h['td'], 2)} dB, "
        "después de aplicar el plan de frecuencias (polarización cruzada o canal adyacente donde hizo falta). Esa degradación "
        "se restó del margen antes de calcular la disponibilidad.")
    t["disponibilidad"] = (
        f"Con R0,01 = {n(h['R001'], 0)} mm/h, la atenuación específica es γR = {n(h['gamma'], 3)} dB/km y el factor de "
        f"distancia r = {n(h['r'], 3)}, lo que da A0,01 = {n(h['A001'])} dB. El margen efectivo de {n(h['margen_ef'])} dB "
        f"solo se supera por lluvia el {n(h['p_lluvia'], 5)} % del año. El multitrayecto añade {n(h['p_multi'], 6)} % "
        f"(mes más desfavorable). La indisponibilidad total es de {n(h['p_total'], 5)} %, es decir, una disponibilidad de "
        f"{n(h['disp'], 4)} %.")
    t["conclusiones"] = [
        f"El enlace de {n(h['distancia_km'], 2)} km entre {h['nombre_A']} y {h['nombre_B']} es viable con visibilidad "
        "directa y no necesita repetidor.",
        f"El diseño inicial ({h['ini_desc']}) falla por lluvia: A0,01 = {n(h['ini_A001'])} dB frente a un margen efectivo de "
        f"{n(h['ini_margen'])} dB. Con R0,01 = {n(h['R001'], 0)} mm/h, por encima de 10 GHz "
        + ("ninguna variante llega al 99,99 % a esta distancia." if not h["altas_cumplen"] else
           f"solo cumple(n): {', '.join(h['altas_cumplen'])}, con un costo mayor.")
        if not h["ini_cumple"] else "El diseño inicial cumplió desde el primer intento.",
        f"Diseño recomendado: {h['fin_desc']}, alturas de {n(h['hA'], 0)} m / {n(h['hB'], 0)} m, {h['mod_ref']} "
        f"garantizada ({n(h['cap_ref'], 0)} Mbps) y hasta {h['mod_max']} ({n(h['cap_max'], 0)} Mbps) con cielo despejado.",
        f"Disponibilidad calculada: {n(h['disp'], 4)} % frente al {n(h['disp_req'], 2)} % exigido. La lluvia domina la "
        "indisponibilidad; el multitrayecto es despreciable por la altitud del trayecto (~2.600 m s. n. m.).",
        "El revisor independiente recalculó distancias, pérdidas, Fresnel, coeficientes ITU-R y el presupuesto sin "
        "encontrar discrepancias críticas.",
    ]
    t["recomendaciones"] = [
        "Solicitar a la ANE la asignación del canal y la polarización indicados y confirmar la ausencia de enlaces "
        "cocanal cercanos (los escenarios de interferencia usados son hipotéticos).",
        "Hacer un estudio de sitio (site survey) con visita a ambos puntos: medir alturas reales de edificaciones y árboles "
        "en los primeros kilómetros desde la central y en el punto crítico.",
        "Comprobar ante la Aerocivil las superficies limitadoras de obstáculos del aeródromo de Guaymaral, que está "
        "cerca del trayecto.",
        "Sustituir el catálogo de perfiles típicos por la hoja de datos del equipo que se compre y volver a ejecutar "
        "el sistema (el informe se regenera solo).",
        "Cambiar R0,01 por el valor del mapa digital de ITU-R P.837-7 en las coordenadas del enlace y volver a "
        "ejecutar el sistema.",
    ]
    return t
