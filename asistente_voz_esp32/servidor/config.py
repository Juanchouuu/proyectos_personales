"""Configuración del servidor, leída de variables de entorno (archivo .env).

Las claves de los proveedores de IA SOLO viven aquí (variables de entorno),
nunca en el firmware ni en el repositorio.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

# Formato de audio acordado con el ESP32 (entrada y salida)
FRECUENCIA_MUESTREO = 16000
BITS_POR_MUESTRA = 16
CANALES = 1

PROMPT_SISTEMA = (
    "Eres un asistente de voz que funciona en un microcontrolador ESP32-S3. "
    "Responde SIEMPRE en español, de forma clara y breve (máximo 3 frases cortas), "
    "porque tu respuesta se convertirá en audio. No uses listas, emojis, markdown "
    "ni símbolos especiales."
)


def _env(nombre: str, defecto: str) -> str:
    return os.getenv(nombre, defecto).strip()


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes")


@dataclass(frozen=True)
class Config:
    # Autenticación del dispositivo (ESP32 real o virtual)
    token_dispositivo: str

    # Proveedores: stt = whisper_local | groq | falso
    #              llm = ollama | groq | falso
    #              tts = edge | gtts | falso
    stt_proveedor: str
    llm_proveedor: str
    tts_proveedor: str

    whisper_modelo: str
    ollama_url: str
    ollama_modelo: str
    groq_api_key: str
    groq_modelo_llm: str
    groq_modelo_stt: str
    edge_voz: str

    # Control de recursos
    max_segundos_grabacion: float
    llm_max_tokens: int
    max_caracteres_respuesta: int
    historial_max_turnos: int
    timeout_servicios_s: float

    # Pruebas de manejo de errores (solo para la práctica)
    permitir_simulacion_fallas: bool

    # Registro de actividad
    archivo_log: Path

    @classmethod
    def desde_entorno(cls) -> "Config":
        load_dotenv(RAIZ / ".env")
        return cls(
            token_dispositivo=_env("DEVICE_TOKEN", ""),
            stt_proveedor=_env("STT_PROVEEDOR", "whisper_local"),
            llm_proveedor=_env("LLM_PROVEEDOR", "ollama"),
            tts_proveedor=_env("TTS_PROVEEDOR", "edge"),
            whisper_modelo=_env("WHISPER_MODELO", "base"),
            ollama_url=_env("OLLAMA_URL", "http://localhost:11434"),
            ollama_modelo=_env("OLLAMA_MODELO", "llama3.2:3b"),
            groq_api_key=_env("GROQ_API_KEY", ""),
            groq_modelo_llm=_env("GROQ_MODELO_LLM", "llama-3.1-8b-instant"),
            groq_modelo_stt=_env("GROQ_MODELO_STT", "whisper-large-v3-turbo"),
            edge_voz=_env("EDGE_VOZ", "es-CO-SalomeNeural"),
            max_segundos_grabacion=float(_env("MAX_SEGUNDOS_GRABACION", "10")),
            llm_max_tokens=int(_env("LLM_MAX_TOKENS", "200")),
            max_caracteres_respuesta=int(_env("MAX_CARACTERES_RESPUESTA", "400")),
            historial_max_turnos=int(_env("HISTORIAL_MAX_TURNOS", "4")),
            timeout_servicios_s=float(_env("TIMEOUT_SERVICIOS_S", "45")),
            permitir_simulacion_fallas=_bool("PERMITIR_SIMULACION_FALLAS", True),
            archivo_log=Path(_env("ARCHIVO_LOG", str(RAIZ / "logs" / "conversaciones.jsonl"))),
        )
