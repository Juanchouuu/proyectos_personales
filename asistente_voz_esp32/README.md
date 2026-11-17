# Asistente de voz con ESP32-S3 y modelos de lenguaje (versión virtual)

Práctica de laboratorio de *Sistemas embebidos e inteligencia artificial*.
Como no hay hardware, el ESP32-S3 se **simula en el navegador**. El servidor Python es el mismo
que usaría la placa real, así que más adelante se puede conectar un ESP32-S3 físico sin cambiarlo.

```
 Navegador: "ESP32 virtual"            Servidor Python (FastAPI)               Servicios de IA (gratis)
 ┌──────────────────────────┐  HTTP   ┌──────────────────────────────┐       ┌──────────────────────┐
 │ botón      → pulsador    │  POST   │ 1. valida token y formato    │──────▶│ STT  Whisper local   │
 │ micrófono  → INMP441     │ ──────▶ │ 2. STT  → texto              │◀──────│ LLM  Ollama / Groq   │
 │ 16 kHz · 16 bits · mono  │  WAV    │ 3. LLM  → respuesta          │       │ TTS  edge-tts / gTTS │
 │ parlantes  → MAX98357A   │ ◀────── │ 4. TTS  → WAV 16 kHz         │       └──────────────────────┘
 │ monitor serie, LEDs      │         │ 5. log, límites, errores     │
 └──────────────────────────┘         └──────────────────────────────┘
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `servidor/` | Servidor Python: API, ciclo STT → LLM → TTS, proveedores, log |
| `web/` | ESP32 virtual (interfaz web) |
| `pruebas/` | Pruebas automáticas y prueba con un archivo de audio |
| `firmware/` | Firmware de referencia para un ESP32-S3 real (no probado en placa) |

## Instalación

**En Windows, sigue la guía paso a paso `GUIA_INSTALACION_WINDOWS.pdf`, que viene en esta carpeta.**

Requisitos: Python 3.10 o superior.

```bash
cd asistente_voz_esp32
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Edita `.env` y cambia `DEVICE_TOKEN` por un valor propio:

```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### Elegir los servicios de IA

Todos son gratuitos. Se eligen en `.env`.

| Etapa | Opción por defecto (sin clave) | Alternativa |
|---|---|---|
| STT | `whisper_local`: Whisper en tu PC. La primera vez descarga el modelo (`base` ≈ 150 MB) | `groq` (más rápido; necesita `GROQ_API_KEY` gratis) |
| LLM | `ollama`: modelo local | `groq` (no necesitas instalar nada, pero pide `GROQ_API_KEY` gratis) o `deepseek` (de pago) |
| TTS | `edge`: voces neuronales en español (necesita internet) | `gtts` |

**Ollama** (LLM local): instálalo desde <https://ollama.com> y descarga el modelo:

```bash
ollama pull llama3.2:3b
```

**Groq**, si tu PC es lento o no quieres instalar Ollama: crea una clave gratuita en
<https://console.groq.com>, ponla en `GROQ_API_KEY` y usa `LLM_PROVEEDOR=groq` y, si quieres, `STT_PROVEEDOR=groq`.

**DeepSeek** (API oficial, de pago pero económica): crea una clave en <https://platform.deepseek.com>
y en `.env` pon:

```ini
LLM_PROVEEDOR=deepseek
DEEPSEEK_API_KEY=sk-...          # solo en .env, nunca en el código
DEEPSEEK_MODELO=deepseek-chat    # recomendado para voz; deepseek-reasoner razona pero tarda más
```

Con `deepseek-reasoner` solo se lee la respuesta final, no el razonamiento. Lo mismo pasa con
`deepseek-r1` en Ollama: su bloque `<think>` se elimina antes de convertir el texto en voz.

Para probar sin internet ni modelos, usa `falso` en las tres etapas: devuelven respuestas fijas.

## Uso

```bash
python -m servidor            # escucha en http://0.0.0.0:8000
```

1. Abre <http://localhost:8000> en Chrome, Edge o Firefox.
2. Escribe el token de tu `.env` en *Configuración del firmware*.
3. Pulsa **Encender ESP32** y permite el acceso al micrófono.
4. Mantén presionado el botón rojo (o la barra espaciadora), haz tu pregunta y suelta.

El navegador solo da acceso al micrófono en `localhost` o con HTTPS. Si abres la interfaz desde
otro equipo de la red, usa el botón **Enviar archivo de audio** o configura HTTPS.

## Cómo cumple la guía

| Requisito | Dónde |
|---|---|
| 3.2 Wi-Fi, botón, grabación 16 kHz/16 bits/mono, HTTP POST, reproducción, consultas repetidas | `web/esp32_virtual.js` (y `firmware/` para la placa real) |
| 3.3 STT, LLM y TTS, y audio devuelto en formato compatible | `servidor/proveedores.py`, `servidor/asistente.py`, `servidor/audio.py` |
| 3.5 Seguridad: claves solo en variables de entorno | `.env` (ignorado por git), `servidor/config.py` |
| 3.5 Autenticación con token | cabecera `Authorization: Bearer <DEVICE_TOKEN>` en `servidor/main.py` |
| 3.5 Control de recursos | `MAX_SEGUNDOS_GRABACION`, `LLM_MAX_TOKENS`, `MAX_CARACTERES_RESPUESTA`, timeouts |
| 3.5 Manejo de errores con mensaje de voz | `MENSAJES_ERROR` en `servidor/asistente.py` |
| 3.5 Registro de actividad | `logs/conversaciones.jsonl`: turno, servicios, errores y tiempos |

## Pruebas (punto 3.6)

**Prueba inicial con un audio grabado**, que revisa STT, LLM y TTS por separado:

```bash
python -m pruebas.probar_con_archivo --crear "¿Cuál es la capital de Colombia?"   # crea pregunta.wav
python -m pruebas.probar_con_archivo pregunta.wav            # prueba cada servicio
python -m pruebas.probar_con_archivo pregunta.wav --http     # prueba el servidor completo
```

**Pruebas automáticas** (con proveedores falsos, no necesitan internet):

```bash
python -m pytest -q
```

**Pruebas en la interfaz:**

| # | Prueba | Cómo hacerla |
|---|---|---|
| 1 | Conectividad | **Encender ESP32**: el LED Wi-Fi queda fijo y el monitor muestra los proveedores |
| 2 | Captura de audio | Graba, luego usa **Escuchar última grabación** o **Descargar WAV** |
| 3 | Reproducción | El parlante virtual vibra y se oye la respuesta |
| 4 | Integración | Haz una pregunta hablada |
| 5 | Manejo de errores | Elige *Pruebas → Simular falla*: red, token, STT, LLM o TTS |
| 6 | Tiempo de respuesta | Panel *Tiempos de respuesta*: desde el envío hasta que empieza a sonar |

El panel **¿Quién hace qué?** y las etiquetas `[ESP32]`, `[SERVIDOR]` e `[IA]` del monitor serie muestran
qué operaciones hace el microcontrolador, cuáles el servidor y cuáles los servicios de IA.

## API del servidor

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/salud` | Estado, proveedores y límites (sin token) |
| `POST` | `/api/consulta` | Cuerpo: WAV 16 kHz/16 bits/mono. Respuesta: WAV del mismo formato |
| `DELETE` | `/api/historial` | Borra el contexto de la conversación del dispositivo |
| `GET` | `/api/registro?n=20` | Últimos turnos del log |

Cabeceras de la consulta: `Authorization: Bearer <token>`, `X-Dispositivo` (opcional) y
`X-Simular-Falla: stt|llm|tts` (solo si `PERMITIR_SIMULACION_FALLAS=true`).
La respuesta trae `X-Estado`, `X-Error`, `X-Transcripcion`, `X-Respuesta` y `X-Tiempos` (codificadas como URL).
Si algo falla, el cuerpo es un **mensaje de voz** que explica el problema (códigos 400, 413, 422, 502 o 504).
Si falla el token, se responde 401 sin audio, y el dispositivo hace un pitido local.

## Usar un ESP32-S3 real

1. Arranca el servidor con `python -m servidor` en un PC o Raspberry Pi de la misma red.
2. Copia `firmware/esp32s3_asistente/secrets.h.example` como `secrets.h` y completa los datos.
3. Abre el `.ino` en Arduino IDE (núcleo esp32 3.x, placa *ESP32S3 Dev Module*, PSRAM *OPI*) y súbelo.

Conexiones sugeridas (se pueden cambiar en el `.ino`):

| Componente | Pin del módulo | GPIO del ESP32-S3 |
|---|---|---|
| INMP441 | SCK / WS / SD | 5 / 6 / 7 (L/R a GND, VDD a 3.3 V) |
| MAX98357A | BCLK / LRC / DIN | 15 / 16 / 17 (VIN a 5 V) |
| Pulsador | — | 4 y GND |
