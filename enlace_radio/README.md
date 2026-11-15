# Enlace de radio punto a punto: sistema multiagente

Práctica de laboratorio *Diseño y validación de un enlace de radio mediante agentes y subagentes de IA*.

Un **agente orquestador** y **9 subagentes** diseñan un radioenlace de ~28 km (≥ 200 Mbps, 99,99 %) entre dos
sitios reales de la Sabana de Bogotá. Usan datos de terreno reales (SRTM) y recomendaciones ITU-R, evalúan
alternativas cuando el diseño no cumple, verifican los cálculos y **generan el PDF automáticamente**.

| Entregable | Archivo |
|---|---|
| 1. Informe técnico (generado por el sistema) | [`salida/informe_enlace_radio.pdf`](salida/informe_enlace_radio.pdf) |
| 2. Descripción del sistema multiagente | [`docs/sistema_multiagente.md`](docs/sistema_multiagente.md) (también en la §2 del PDF) |
| 3. Código fuente y datos | `src/`, `config/`, `data/`, `tests/` |

## Resultado actual

* Diseño inicial (13 GHz, antenas de 0,6 m): **no cumple** (99,74 %; la lluvia supera el margen).
* Se evaluaron 88 diseños y 9 cumplen. Seleccionado: **7 GHz, canal de 28 MHz, pol. V, antenas de 0,9 m,
  alturas de 21 m y 12 m**: 512QAM = 200 Mbps garantizados (hasta 245 Mbps con 2048QAM) y disponibilidad del **99,9939 %**.
* Revisión independiente: 27 verificaciones, 0 fallos críticos.

## Cómo ejecutarlo

```bash
cd enlace_radio
pip install -r requirements.txt

# Motor de reglas (determinista, sin clave de API)
python generar_informe.py --motor reglas -v

# Orquestador LLM (Claude): necesita ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=...
python generar_informe.py --motor claude          # modelo por defecto: claude-opus-5-5

# Sin Internet: usa el perfil ya extraído en data/perfil_terreno.csv
python generar_informe.py --sin-red

# Pruebas
python -m pytest -q
```

La primera ejecución descarga la tesela SRTM `N04W075` (~16 MB) en `data/dem/`. Las siguientes la reutilizan.
Cada ejecución regenera `salida/informe_enlace_radio.pdf`, `salida/resultados.json` y las figuras de `salida/figuras/`.

## Cambiar el escenario

Todo se configura en [`config/escenario.json`](config/escenario.json): sitios, requisitos, clima (R0,01, dN1),
clutter, criterios de despeje y escenarios de interferencia. El catálogo de bandas, radios y antenas está en
[`data/equipos.json`](data/equipos.json). Después de cambiar algo, vuelve a ejecutar y el informe se regenera.

## Estructura

```
enlace_radio/
├── generar_informe.py         # punto de entrada
├── config/escenario.json      # datos de entrada
├── data/equipos.json          # catálogo de bandas, radios y antenas
├── data/perfil_terreno.csv    # perfil SRTM extraído (respaldo sin red)
├── src/enlace/
│   ├── agentes/               # orquestador, subagentes, pizarra, redacción
│   ├── herramientas/          # geo, DEM, propagación, ITU-R, interferencia, gráficas, PDF
│   └── llm.py                 # orquestador Claude (tool use) + verificador de cifras
├── tests/                     # pruebas unitarias y de flujo completo
├── docs/sistema_multiagente.md
└── salida/                    # informe PDF y resultados.json (generados)
```
