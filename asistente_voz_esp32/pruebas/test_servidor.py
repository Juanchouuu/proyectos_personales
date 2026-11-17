"""Pruebas automáticas del servidor con proveedores falsos (no necesitan internet).

Ejecutar desde la carpeta asistente_voz_esp32:   python -m pytest -q
"""

import json
import math
import struct
from dataclasses import replace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from servidor.audio import leer_wav, pcm_a_wav
from servidor.asistente import limitar_texto
from servidor.config import Config
from servidor.main import crear_app

TOKEN = "token-de-prueba"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def wav_tono(segundos: float, frecuencia: int = 16000, canales: int = 1) -> bytes:
    n = int(frecuencia * segundos)
    muestras = [int(8000 * math.sin(2 * math.pi * 300 * i / frecuencia)) for i in range(n)]
    if canales == 1:
        return pcm_a_wav(struct.pack(f"<{n}h", *muestras), frecuencia)
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(2)
        w.setframerate(frecuencia)
        w.writeframes(struct.pack(f"<{n * canales}h", *[m for m in muestras for _ in range(canales)]))
    return buf.getvalue()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE_TOKEN", TOKEN)
    base = Config.desde_entorno()
    return replace(
        base, token_dispositivo=TOKEN, stt_proveedor="falso", llm_proveedor="falso", tts_proveedor="falso",
        max_segundos_grabacion=5, permitir_simulacion_fallas=True, archivo_log=tmp_path / "log.jsonl",
    )


@pytest.fixture
def cliente(cfg):
    with TestClient(crear_app(cfg)) as c:
        yield c


def test_salud(cliente):
    r = cliente.get("/api/salud")
    assert r.status_code == 200
    assert r.json()["formato_audio"] == {"frecuencia": 16000, "bits": 16, "canales": 1}


def test_interfaz_web(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "ESP32-S3" in r.text
    assert cliente.get("/web/esp32_virtual.js").status_code == 200


def test_sin_token_rechaza(cliente):
    assert cliente.post("/api/consulta", content=wav_tono(1)).status_code == 401
    r = cliente.post("/api/consulta", content=wav_tono(1), headers={"Authorization": "Bearer otro"})
    assert r.status_code == 401


def test_consulta_completa(cliente, cfg):
    r = cliente.post("/api/consulta", content=wav_tono(1.5), headers={**AUTH, "X-Dispositivo": "prueba"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.headers["X-Estado"] == "ok"
    info = leer_wav(r.content)
    assert (info.frecuencia, info.bits, info.canales) == (16000, 16, 1)
    assert info.duracion_s > 0.3
    assert "1.5 segundos" in unquote(r.headers["X-Transcripcion"])
    tiempos = json.loads(unquote(r.headers["X-Tiempos"]))
    assert {"stt", "llm", "tts", "total_servidor"} <= tiempos.keys()

    # registro de actividad
    lineas = cfg.archivo_log.read_text(encoding="utf-8").splitlines()
    entrada = json.loads(lineas[-1])
    assert entrada["estado"] == "ok" and entrada["dispositivo"] == "prueba"
    assert entrada["proveedores"]["llm"] == "falso"
    assert cliente.get("/api/registro", headers=AUTH).json()[-1]["turno"] == r.headers["X-Turno"]


def test_formato_incorrecto(cliente):
    r = cliente.post("/api/consulta", content=wav_tono(1, frecuencia=44100), headers=AUTH)
    assert r.status_code == 400 and r.headers["content-type"] == "audio/wav"
    r = cliente.post("/api/consulta", content=wav_tono(1, canales=2), headers=AUTH)
    assert r.status_code == 400
    r = cliente.post("/api/consulta", content=b"no es audio", headers=AUTH)
    assert r.status_code == 400


def test_grabacion_demasiado_larga(cliente):
    r = cliente.post("/api/consulta", content=wav_tono(7), headers=AUTH)
    assert r.status_code == 413
    assert unquote(r.headers["X-Error"]).startswith("grabacion_larga")
    assert leer_wav(r.content).duracion_s > 0  # mensaje de voz


@pytest.mark.parametrize("etapa", ["stt", "llm", "tts"])
def test_fallas_simuladas_devuelven_voz(cliente, cfg, etapa):
    r = cliente.post("/api/consulta", content=wav_tono(1), headers={**AUTH, "X-Simular-Falla": etapa})
    assert r.status_code == 502
    assert r.headers["X-Estado"] == "error"
    assert unquote(r.headers["X-Error"]).startswith(etapa)
    assert leer_wav(r.content).duracion_s > 0
    entrada = json.loads(cfg.archivo_log.read_text(encoding="utf-8").splitlines()[-1])
    assert entrada["estado"] == "error" and entrada["falla_simulada"] == etapa


def test_simulacion_desactivada(cfg):
    with TestClient(crear_app(replace(cfg, permitir_simulacion_fallas=False))) as c:
        r = c.post("/api/consulta", content=wav_tono(1), headers={**AUTH, "X-Simular-Falla": "llm"})
        assert r.status_code == 200


def test_error_real_del_llm(cliente):
    asistente = cliente.app.state.asistente

    async def falla(_):
        raise ConnectionError("servicio caído")

    asistente.llm.responder = falla
    r = cliente.post("/api/consulta", content=wav_tono(1), headers=AUTH)
    assert r.status_code == 502
    assert "ConnectionError" in unquote(r.headers["X-Error"])


def test_historial_y_reinicio(cliente):
    asistente = cliente.app.state.asistente
    for _ in range(6):
        cliente.post("/api/consulta", content=wav_tono(1), headers={**AUTH, "X-Dispositivo": "d1"})
    assert len(asistente.historial["d1"]) == asistente.cfg.historial_max_turnos * 2
    assert cliente.delete("/api/historial", headers={**AUTH, "X-Dispositivo": "d1"}).status_code == 200
    assert "d1" not in asistente.historial


def test_limitar_texto():
    texto = "Primera frase. Segunda frase bastante más larga que la anterior. Tercera."
    assert limitar_texto(texto, 70) == "Primera frase. Segunda frase bastante más larga que la anterior."
    assert limitar_texto(texto, 40) == "Primera frase. Segunda frase bastante..."
    assert limitar_texto("**Hola** mundo", 100) == "Hola mundo"
    assert len(limitar_texto("palabra " * 100, 50)) <= 53


# ---------------------------------------------------------------- DeepSeek (API simulada)

def _api_deepseek_simulada(peticiones: list):
    import httpx

    def responder(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant",
            "content": "La capital de Colombia es Bogotá.",
            "reasoning_content": "esto no se debe leer",
        }}]})

    return httpx.MockTransport(responder)


def test_deepseek_en_el_flujo_completo(cfg, monkeypatch):
    from servidor.proveedores import LLMDeepSeek

    peticiones = []
    monkeypatch.setattr(LLMDeepSeek, "transporte", _api_deepseek_simulada(peticiones))
    cfg_ds = replace(cfg, llm_proveedor="deepseek", deepseek_api_key="sk-prueba", deepseek_modelo="deepseek-chat")
    with TestClient(crear_app(cfg_ds)) as c:
        assert c.get("/api/salud").json()["proveedores"]["llm"] == "deepseek:deepseek-chat"
        r = c.post("/api/consulta", content=wav_tono(1), headers=AUTH)

    assert r.status_code == 200
    assert unquote(r.headers["X-Respuesta"]) == "La capital de Colombia es Bogotá."
    peticion = peticiones[0]
    assert str(peticion.url) == "https://api.deepseek.com/chat/completions"
    assert peticion.headers["Authorization"] == "Bearer sk-prueba"
    cuerpo = json.loads(peticion.content)
    assert cuerpo["model"] == "deepseek-chat"
    assert cuerpo["max_tokens"] == cfg.llm_max_tokens
    assert cuerpo["messages"][0]["role"] == "system"


def test_deepseek_sin_clave_da_error_de_voz(cfg):
    with TestClient(crear_app(replace(cfg, llm_proveedor="deepseek", deepseek_api_key=""))) as c:
        r = c.post("/api/consulta", content=wav_tono(1), headers=AUTH)
    assert r.status_code == 502
    assert "DEEPSEEK_API_KEY" in unquote(r.headers["X-Error"])
    assert leer_wav(r.content).duracion_s > 0


def test_se_quita_el_razonamiento_think():
    texto = "<think>\nEl usuario pregunta por la capital...\n</think>\n\nEs Bogotá."
    assert limitar_texto(texto, 400) == "Es Bogotá."
