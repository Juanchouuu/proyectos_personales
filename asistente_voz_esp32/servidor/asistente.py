"""Ciclo de procesamiento de una consulta: audio -> STT -> LLM -> TTS -> audio.

Aquí también se aplican el control de recursos, el manejo de errores
(con mensajes de voz) y el registro de cada turno.
"""

import asyncio
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .audio import AudioInvalido, a_wav_esp32, leer_wav, tono, validar_formato_esp32
from .config import PROMPT_SISTEMA, Config
from .proveedores import ErrorServicio, crear_proveedores
from .registro import Registro

# Mensajes de voz para cada tipo de error: (código HTTP, texto hablado)
MENSAJES_ERROR = {
    "audio_invalido": (400, "El audio que recibí no tiene el formato correcto."),
    "grabacion_larga": (413, "La grabación es demasiado larga. Intenta con una pregunta más corta."),
    "sin_voz": (422, "No logré escucharte. Intenta de nuevo hablando cerca del micrófono."),
    "stt": (502, "No pude reconocer tu voz porque el servicio de reconocimiento falló."),
    "llm": (502, "El modelo de lenguaje no está disponible en este momento. Intenta más tarde."),
    "tts": (502, "Tengo una respuesta, pero no pude convertirla en voz."),
    "timeout": (504, "Un servicio tardó demasiado en responder. Intenta de nuevo."),
}


@dataclass
class Resultado:
    turno: str
    wav: bytes
    codigo_http: int = 200
    estado: str = "ok"
    error: str | None = None
    transcripcion: str = ""
    respuesta: str = ""
    tiempos_ms: dict = field(default_factory=dict)
    proveedores: dict = field(default_factory=dict)


def limitar_texto(texto: str, maximo: int) -> str:
    """Limpia símbolos que no se leen bien en voz y recorta respetando frases."""
    # Modelos de razonamiento (p. ej. deepseek-r1 en Ollama) escriben <think>...</think>:
    # eso no se debe leer en voz alta.
    texto = re.sub(r"<think>.*?(</think>|$)", "", texto, flags=re.DOTALL | re.IGNORECASE)
    texto = re.sub(r"[*#_`>|~]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= maximo:
        return texto
    corte = texto[:maximo]
    fin_frase = max(corte.rfind(". "), corte.rfind("! "), corte.rfind("? "), corte.rfind("."))
    if fin_frase > maximo * 0.4:
        return corte[: fin_frase + 1]
    return corte[: corte.rfind(" ")].rstrip(",;:") + "..."


class Asistente:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.stt, self.llm, self.tts = crear_proveedores(cfg)
        self.registro = Registro(cfg.archivo_log)
        self.historial: dict[str, deque] = defaultdict(lambda: deque(maxlen=cfg.historial_max_turnos * 2))
        self._audios_error: dict[str, bytes] = {}

    @property
    def nombres_proveedores(self) -> dict:
        return {"stt": self.stt.nombre, "llm": self.llm.nombre, "tts": self.tts.nombre}

    # ------------------------------------------------------------ errores con voz

    async def _audio_error(self, codigo: str, tts_disponible: bool = True) -> bytes:
        """Devuelve el mensaje de error en voz (cacheado). Si el TTS no sirve, pitidos."""
        if codigo in self._audios_error:
            return self._audios_error[codigo]
        if tts_disponible:
            try:
                audio = await asyncio.wait_for(self.tts.sintetizar(MENSAJES_ERROR[codigo][1]), 15)
                wav = await asyncio.to_thread(a_wav_esp32, audio)
                self._audios_error[codigo] = wav
                return wav
            except Exception:
                pass
        return tono()

    async def precargar_mensajes_error(self) -> None:
        """Genera de antemano los mensajes de error, para tenerlos aunque el TTS falle luego."""
        for codigo in MENSAJES_ERROR:
            await self._audio_error(codigo)

    # ------------------------------------------------------------ etapas

    async def _etapa(self, nombre: str, corrutina, simular: str | None):
        if simular == nombre:
            corrutina.close()
            raise ErrorServicio(nombre, "falla simulada para pruebas")
        try:
            return await asyncio.wait_for(corrutina, self.cfg.timeout_servicios_s)
        except asyncio.TimeoutError as e:
            raise ErrorServicio("timeout", f"{nombre} superó {self.cfg.timeout_servicios_s:.0f} s") from e
        except ErrorServicio:
            raise
        except Exception as e:
            raise ErrorServicio(nombre, f"{type(e).__name__}: {e}") from e

    async def procesar(self, wav_entrada: bytes, dispositivo: str, simular: str | None = None) -> Resultado:
        turno = uuid.uuid4().hex[:8]
        res = Resultado(turno=turno, wav=b"", proveedores=self.nombres_proveedores)
        t0 = time.perf_counter()
        duracion = 0.0
        etapa_tts_ok = True

        def ms(desde: float) -> int:
            return round((time.perf_counter() - desde) * 1000)

        try:
            # 1. Validar audio (formato y duración máxima)
            try:
                info = leer_wav(wav_entrada)
                validar_formato_esp32(info)
            except AudioInvalido as e:
                raise ErrorServicio("audio_invalido", str(e)) from e
            duracion = info.duracion_s
            if duracion > self.cfg.max_segundos_grabacion + 0.5:
                raise ErrorServicio(
                    "grabacion_larga", f"{duracion:.1f} s > {self.cfg.max_segundos_grabacion:.0f} s"
                )

            # 2. STT
            t = time.perf_counter()
            res.transcripcion = await self._etapa("stt", self.stt.transcribir(info, wav_entrada), simular)
            res.tiempos_ms["stt"] = ms(t)
            if len(res.transcripcion.strip(" .,¿?¡!")) < 2:
                raise ErrorServicio("sin_voz", "la transcripción está vacía")

            # 3. LLM (con un historial corto para mantener la conversación)
            historial = self.historial[dispositivo]
            mensajes = [{"role": "system", "content": PROMPT_SISTEMA}, *historial,
                        {"role": "user", "content": res.transcripcion}]
            t = time.perf_counter()
            texto = await self._etapa("llm", self.llm.responder(mensajes), simular)
            res.tiempos_ms["llm"] = ms(t)
            res.respuesta = limitar_texto(texto, self.cfg.max_caracteres_respuesta)
            if not res.respuesta:
                raise ErrorServicio("llm", "el modelo devolvió una respuesta vacía")

            # 4. TTS y conversión al formato del ESP32
            t = time.perf_counter()
            try:
                audio = await self._etapa("tts", self.tts.sintetizar(res.respuesta), simular)
                res.wav = await asyncio.to_thread(a_wav_esp32, audio)
            except ErrorServicio:
                etapa_tts_ok = False
                raise
            except Exception as e:
                etapa_tts_ok = False
                raise ErrorServicio("tts", f"conversión de audio: {e}") from e
            res.tiempos_ms["tts"] = ms(t)

            historial.append({"role": "user", "content": res.transcripcion})
            historial.append({"role": "assistant", "content": res.respuesta})

        except ErrorServicio as e:
            codigo = e.etapa if e.etapa in MENSAJES_ERROR else "llm"
            if codigo == "timeout" and "tts" in e.detalle:
                etapa_tts_ok = False
            res.estado = "error"
            res.error = f"{codigo}: {e.detalle}"
            res.codigo_http = MENSAJES_ERROR[codigo][0]
            res.wav = await self._audio_error(codigo, tts_disponible=etapa_tts_ok)

        res.tiempos_ms["total_servidor"] = ms(t0)
        self.registro.escribir({
            "turno": turno,
            "dispositivo": dispositivo,
            "estado": res.estado,
            "error": res.error,
            "duracion_audio_s": round(duracion, 2),
            "transcripcion": res.transcripcion,
            "respuesta": res.respuesta,
            "proveedores": res.proveedores,
            "tiempos_ms": res.tiempos_ms,
            "falla_simulada": simular,
        })
        return res

    def reiniciar_historial(self, dispositivo: str) -> None:
        self.historial.pop(dispositivo, None)
