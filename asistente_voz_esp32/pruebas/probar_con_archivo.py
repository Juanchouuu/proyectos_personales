"""Prueba inicial de la guía: usar un audio ya grabado para verificar STT, LLM y TTS.

Modo "servicios" (por defecto): prueba cada etapa por separado, sin HTTP.
    python -m pruebas.probar_con_archivo mi_pregunta.wav

Modo "http": envía el audio al servidor como lo haría el ESP32.
    python -m pruebas.probar_con_archivo mi_pregunta.wav --http --url http://localhost:8000

Si no tienes un audio, crea uno con el TTS configurado:
    python -m pruebas.probar_con_archivo --crear "¿Cuál es la capital de Colombia?"

El audio puede estar en cualquier formato (wav, mp3, m4a...): se convierte a 16 kHz / 16 bits / mono.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import httpx

from servidor.audio import a_wav_esp32, leer_wav
from servidor.config import PROMPT_SISTEMA, Config
from servidor.proveedores import crear_proveedores


def paso(nombre: str):
    print(f"\n== {nombre} " + "=" * (50 - len(nombre)))


async def probar_servicios(wav: bytes, cfg: Config) -> None:
    stt, llm, tts = crear_proveedores(cfg)
    info = leer_wav(wav)
    print(f"Audio: {info.duracion_s:.2f} s, {info.frecuencia} Hz, {info.bits} bits, {info.canales} canal(es)")

    paso(f"STT  ({stt.nombre})")
    t = time.perf_counter()
    texto = await stt.transcribir(info, wav)
    print(f"[{(time.perf_counter() - t) * 1000:.0f} ms] {texto!r}")

    paso(f"LLM  ({llm.nombre})")
    t = time.perf_counter()
    respuesta = await llm.responder([{"role": "system", "content": PROMPT_SISTEMA},
                                     {"role": "user", "content": texto}])
    print(f"[{(time.perf_counter() - t) * 1000:.0f} ms] {respuesta!r}")

    paso(f"TTS  ({tts.nombre})")
    t = time.perf_counter()
    salida = a_wav_esp32(await tts.sintetizar(respuesta))
    print(f"[{(time.perf_counter() - t) * 1000:.0f} ms] {len(salida) / 1024:.1f} KB")
    Path("respuesta_servicios.wav").write_bytes(salida)
    print("\nOK. Respuesta guardada en respuesta_servicios.wav")


def probar_http(wav: bytes, url: str, token: str) -> None:
    t = time.perf_counter()
    r = httpx.post(f"{url.rstrip('/')}/api/consulta", content=wav, timeout=120,
                   headers={"Authorization": f"Bearer {token}", "X-Dispositivo": "prueba-archivo"})
    total = (time.perf_counter() - t) * 1000
    print(f"HTTP {r.status_code}  ({total:.0f} ms)")
    if r.headers.get("content-type", "").startswith("audio/wav"):
        for h in ("X-Estado", "X-Error", "X-Transcripcion", "X-Respuesta", "X-Tiempos"):
            valor = unquote(r.headers.get(h, ""))
            if valor:
                print(f"  {h}: {valor}")
        Path("respuesta_http.wav").write_bytes(r.content)
        print("Audio guardado en respuesta_http.wav")
    else:
        print(r.text)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio", nargs="?", help="archivo de audio con la pregunta")
    p.add_argument("--crear", metavar="TEXTO", help="crea pregunta.wav con el TTS configurado y termina")
    p.add_argument("--http", action="store_true", help="enviar al servidor en vez de probar los servicios")
    p.add_argument("--url", default="http://localhost:8000")
    a = p.parse_args()
    cfg = Config.desde_entorno()

    if a.crear:
        _, _, tts = crear_proveedores(cfg)
        wav = a_wav_esp32(asyncio.run(tts.sintetizar(a.crear)))
        Path("pregunta.wav").write_bytes(wav)
        print(f"Creado pregunta.wav con {tts.nombre}")
        return 0
    if not a.audio:
        p.error("indica un archivo de audio o usa --crear")

    wav = a_wav_esp32(Path(a.audio).read_bytes())
    if a.http:
        if not cfg.token_dispositivo:
            p.error("falta DEVICE_TOKEN en .env")
        probar_http(wav, a.url, cfg.token_dispositivo)
    else:
        asyncio.run(probar_servicios(wav, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
