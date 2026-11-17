"""Proveedores de IA intercambiables para las tres etapas: STT, LLM y TTS.

Se eligen con variables de entorno (STT_PROVEEDOR, LLM_PROVEEDOR, TTS_PROVEEDOR).
Todos los proveedores por defecto son gratuitos:

- STT  whisper_local : faster-whisper en el propio computador (sin clave).
       groq          : Whisper en la nube de Groq (clave gratuita).
- LLM  ollama        : modelo local con Ollama (sin clave).
       groq          : Llama en la nube de Groq (clave gratuita).
       deepseek      : API de DeepSeek (clave de pago, económica).
- TTS  edge          : voces neuronales de Microsoft Edge (sin clave).
       gtts          : Google Translate TTS (sin clave).
- falso: respuestas fijas para probar sin internet ni modelos.
"""

import asyncio
import io

import httpx

from .audio import InfoWav, tono, wav_a_float32
from .config import Config

GROQ_URL = "https://api.groq.com/openai/v1"


class ErrorServicio(Exception):
    """Falla de un servicio externo, indicando la etapa donde ocurrió."""

    def __init__(self, etapa: str, detalle: str):
        super().__init__(f"[{etapa}] {detalle}")
        self.etapa = etapa
        self.detalle = detalle


def _clave_groq(cfg: Config) -> str:
    if not cfg.groq_api_key:
        raise RuntimeError("Falta GROQ_API_KEY en el archivo .env")
    return cfg.groq_api_key


# ---------------------------------------------------------------- STT


class STTWhisperLocal:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.nombre = f"whisper_local:{cfg.whisper_modelo}"
        self._modelo = None

    def _cargar(self):
        if self._modelo is None:
            from faster_whisper import WhisperModel  # import perezoso: es pesado

            self._modelo = WhisperModel(self.cfg.whisper_modelo, device="cpu", compute_type="int8")
        return self._modelo

    def _transcribir(self, info: InfoWav) -> str:
        segmentos, _ = self._cargar().transcribe(
            wav_a_float32(info), language="es", beam_size=1, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segmentos).strip()

    async def transcribir(self, info: InfoWav, wav: bytes) -> str:
        return await asyncio.to_thread(self._transcribir, info)


class STTGroq:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.nombre = f"groq:{cfg.groq_modelo_stt}"

    async def transcribir(self, info: InfoWav, wav: bytes) -> str:
        async with httpx.AsyncClient(timeout=self.cfg.timeout_servicios_s) as cliente:
            r = await cliente.post(
                f"{GROQ_URL}/audio/transcriptions",
                headers={"Authorization": f"Bearer {_clave_groq(self.cfg)}"},
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"model": self.cfg.groq_modelo_stt, "language": "es", "response_format": "json"},
            )
            r.raise_for_status()
            return r.json().get("text", "").strip()


class STTFalso:
    nombre = "falso"

    def __init__(self, cfg: Config):
        pass

    async def transcribir(self, info: InfoWav, wav: bytes) -> str:
        return f"Esta es una prueba de {info.duracion_s:.1f} segundos de audio"


# ---------------------------------------------------------------- LLM


class LLMOllama:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.nombre = f"ollama:{cfg.ollama_modelo}"

    async def responder(self, mensajes: list[dict]) -> str:
        async with httpx.AsyncClient(timeout=self.cfg.timeout_servicios_s) as cliente:
            r = await cliente.post(
                f"{self.cfg.ollama_url}/api/chat",
                json={
                    "model": self.cfg.ollama_modelo,
                    "messages": mensajes,
                    "stream": False,
                    "options": {"num_predict": self.cfg.llm_max_tokens, "temperature": 0.6},
                },
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()


class LLMCompatibleOpenAI:
    """Cualquier API con el formato /chat/completions de OpenAI (Groq, DeepSeek, ...)."""

    transporte: httpx.AsyncBaseTransport | None = None  # las pruebas lo reemplazan

    def __init__(self, cfg: Config, proveedor: str, url: str, clave: str, variable_clave: str, modelo: str):
        self.cfg = cfg
        self.nombre = f"{proveedor}:{modelo}"
        self.url = url.rstrip("/")
        self.clave = clave
        self.variable_clave = variable_clave
        self.modelo = modelo

    async def responder(self, mensajes: list[dict]) -> str:
        if not self.clave:
            raise RuntimeError(f"Falta {self.variable_clave} en el archivo .env")
        async with httpx.AsyncClient(timeout=self.cfg.timeout_servicios_s, transport=self.transporte) as cliente:
            r = await cliente.post(
                f"{self.url}/chat/completions",
                headers={"Authorization": f"Bearer {self.clave}"},
                json={
                    "model": self.modelo,
                    "messages": mensajes,
                    "max_tokens": self.cfg.llm_max_tokens,
                    "temperature": 0.6,
                    "stream": False,
                },
            )
            r.raise_for_status()
            # deepseek-reasoner devuelve su razonamiento aparte (reasoning_content); solo se usa content
            return r.json()["choices"][0]["message"]["content"].strip()


class LLMGroq(LLMCompatibleOpenAI):
    def __init__(self, cfg: Config):
        super().__init__(cfg, "groq", GROQ_URL, cfg.groq_api_key, "GROQ_API_KEY", cfg.groq_modelo_llm)


class LLMDeepSeek(LLMCompatibleOpenAI):
    def __init__(self, cfg: Config):
        super().__init__(cfg, "deepseek", cfg.deepseek_url, cfg.deepseek_api_key, "DEEPSEEK_API_KEY",
                         cfg.deepseek_modelo)


class LLMFalso:
    nombre = "falso"

    def __init__(self, cfg: Config):
        pass

    async def responder(self, mensajes: list[dict]) -> str:
        return f"Recibí tu pregunta: {mensajes[-1]['content']}. Esta es una respuesta de prueba."


# ---------------------------------------------------------------- TTS


class TTSEdge:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.nombre = f"edge:{cfg.edge_voz}"

    async def sintetizar(self, texto: str) -> bytes:
        import edge_tts

        mp3 = bytearray()
        async for parte in edge_tts.Communicate(texto, self.cfg.edge_voz).stream():
            if parte["type"] == "audio":
                mp3 += parte["data"]
        if not mp3:
            raise RuntimeError("edge-tts no devolvió audio")
        return bytes(mp3)


class TTSGtts:
    nombre = "gtts:es"

    def __init__(self, cfg: Config):
        pass

    def _sintetizar(self, texto: str) -> bytes:
        from gtts import gTTS

        buf = io.BytesIO()
        gTTS(texto, lang="es", tld="com.co").write_to_fp(buf)
        return buf.getvalue()

    async def sintetizar(self, texto: str) -> bytes:
        return await asyncio.to_thread(self._sintetizar, texto)


class TTSFalso:
    nombre = "falso"

    def __init__(self, cfg: Config):
        pass

    async def sintetizar(self, texto: str) -> bytes:
        return tono((523, 659, 784), 0.2)


# ---------------------------------------------------------------- fábrica

_STT = {"whisper_local": STTWhisperLocal, "groq": STTGroq, "falso": STTFalso}
_LLM = {"ollama": LLMOllama, "groq": LLMGroq, "deepseek": LLMDeepSeek, "falso": LLMFalso}
_TTS = {"edge": TTSEdge, "gtts": TTSGtts, "falso": TTSFalso}


def _crear(tabla: dict, nombre: str, tipo: str, cfg: Config):
    if nombre not in tabla:
        raise ValueError(f"{tipo}_PROVEEDOR='{nombre}' no existe. Opciones: {', '.join(tabla)}")
    return tabla[nombre](cfg)


def crear_proveedores(cfg: Config):
    return (
        _crear(_STT, cfg.stt_proveedor, "STT", cfg),
        _crear(_LLM, cfg.llm_proveedor, "LLM", cfg),
        _crear(_TTS, cfg.tts_proveedor, "TTS", cfg),
    )
