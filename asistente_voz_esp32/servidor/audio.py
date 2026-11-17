"""Utilidades de audio: validar el WAV del ESP32 y convertir la respuesta a su formato."""

import io
import math
import struct
import wave
from dataclasses import dataclass

import av
import numpy as np

from .config import BITS_POR_MUESTRA, CANALES, FRECUENCIA_MUESTREO


class AudioInvalido(ValueError):
    """El audio recibido no cumple el formato acordado."""


@dataclass
class InfoWav:
    frecuencia: int
    bits: int
    canales: int
    duracion_s: float
    pcm: bytes


def leer_wav(datos: bytes) -> InfoWav:
    """Lee un WAV PCM y devuelve su información. Lanza AudioInvalido si no se puede leer."""
    try:
        with wave.open(io.BytesIO(datos), "rb") as w:
            frecuencia = w.getframerate()
            bits = w.getsampwidth() * 8
            canales = w.getnchannels()
            n = w.getnframes()
            pcm = w.readframes(n)
    except (wave.Error, EOFError, struct.error) as e:
        raise AudioInvalido(f"No es un archivo WAV válido: {e}") from e
    duracion = n / frecuencia if frecuencia else 0.0
    return InfoWav(frecuencia, bits, canales, duracion, pcm)


def validar_formato_esp32(info: InfoWav) -> None:
    """Comprueba que el audio sea 16 kHz, 16 bits, mono (requisito de la práctica)."""
    if (info.frecuencia, info.bits, info.canales) != (FRECUENCIA_MUESTREO, BITS_POR_MUESTRA, CANALES):
        raise AudioInvalido(
            f"Formato {info.frecuencia} Hz / {info.bits} bits / {info.canales} canal(es); "
            f"se esperaba {FRECUENCIA_MUESTREO} Hz / {BITS_POR_MUESTRA} bits / mono"
        )


def pcm_a_wav(pcm: bytes, frecuencia: int = FRECUENCIA_MUESTREO) -> bytes:
    """Empaqueta PCM 16 bits mono en un WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(CANALES)
        w.setsampwidth(BITS_POR_MUESTRA // 8)
        w.setframerate(frecuencia)
        w.writeframes(pcm)
    return buf.getvalue()


def a_wav_esp32(datos: bytes) -> bytes:
    """Convierte cualquier audio (MP3, WAV, ...) a WAV 16 kHz / 16 bits / mono.

    Es el formato que el ESP32 puede reproducir directamente por el MAX98357A.
    """
    entrada = av.open(io.BytesIO(datos))
    remuestreador = av.AudioResampler(format="s16", layout="mono", rate=FRECUENCIA_MUESTREO)
    pcm = bytearray()
    for frame in entrada.decode(audio=0):
        for f in remuestreador.resample(frame):
            pcm += f.to_ndarray().tobytes()
    for f in remuestreador.resample(None):  # vaciar el remuestreador
        pcm += f.to_ndarray().tobytes()
    entrada.close()
    return pcm_a_wav(bytes(pcm))


def wav_a_float32(info: InfoWav) -> np.ndarray:
    """PCM 16 bits mono -> arreglo float32 en [-1, 1] (entrada de Whisper local)."""
    return np.frombuffer(info.pcm, dtype=np.int16).astype(np.float32) / 32768.0


def tono(frecuencias=(880, 660), duracion_s: float = 0.25) -> bytes:
    """Genera pitidos en WAV. Último recurso si ni siquiera el TTS funciona."""
    muestras = []
    for f in frecuencias:
        n = int(FRECUENCIA_MUESTREO * duracion_s)
        for i in range(n):
            envolvente = min(1.0, i / 200, (n - i) / 200)
            muestras.append(int(12000 * envolvente * math.sin(2 * math.pi * f * i / FRECUENCIA_MUESTREO)))
        muestras.extend([0] * int(FRECUENCIA_MUESTREO * 0.08))
    return pcm_a_wav(struct.pack(f"<{len(muestras)}h", *muestras))
