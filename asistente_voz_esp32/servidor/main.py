"""Servidor intermedio del asistente de voz (FastAPI).

Ejecutar desde la carpeta asistente_voz_esp32:
    python -m servidor

Endpoints:
    GET    /                -> ESP32 virtual (interfaz web)
    GET    /api/salud       -> estado del servidor (lo usa el ESP32 para "conectarse")
    POST   /api/consulta    -> recibe WAV 16 kHz/16 bits/mono y devuelve WAV de respuesta
    DELETE /api/historial   -> borra el contexto de conversación del dispositivo
    GET    /api/registro    -> últimos turnos del archivo de log
"""

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .asistente import Asistente
from .config import BITS_POR_MUESTRA, CANALES, FRECUENCIA_MUESTREO, Config

log = logging.getLogger("asistente")
CARPETA_WEB = Path(__file__).resolve().parent.parent / "web"
MAX_BYTES_AUDIO = 2 * 1024 * 1024  # límite duro del cuerpo de la petición
CABECERAS_EXPUESTAS = [
    "X-Turno", "X-Estado", "X-Error", "X-Transcripcion", "X-Respuesta", "X-Tiempos", "X-Proveedores",
]


def crear_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.desde_entorno()
    if not cfg.token_dispositivo:
        raise RuntimeError("Falta DEVICE_TOKEN en el archivo .env (copia .env.example a .env)")
    asistente = Asistente(cfg)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        log.info("Proveedores: %s", asistente.nombres_proveedores)
        tarea = asyncio.create_task(asistente.precargar_mensajes_error())
        yield
        tarea.cancel()

    app = FastAPI(title="Asistente de voz ESP32-S3", lifespan=ciclo_de_vida)
    app.state.asistente = asistente
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=CABECERAS_EXPUESTAS,
    )

    def autenticar(authorization: str | None) -> None:
        esperado = f"Bearer {cfg.token_dispositivo}"
        if not authorization or not hmac.compare_digest(authorization.encode(), esperado.encode()):
            raise HTTPException(status_code=401, detail="Token de dispositivo inválido o ausente")

    @app.get("/api/salud")
    async def salud():
        return {
            "estado": "ok",
            "proveedores": asistente.nombres_proveedores,
            "formato_audio": {"frecuencia": FRECUENCIA_MUESTREO, "bits": BITS_POR_MUESTRA, "canales": CANALES},
            "limites": {
                "max_segundos_grabacion": cfg.max_segundos_grabacion,
                "max_caracteres_respuesta": cfg.max_caracteres_respuesta,
                "llm_max_tokens": cfg.llm_max_tokens,
            },
            "simulacion_fallas": cfg.permitir_simulacion_fallas,
        }

    @app.post("/api/consulta")
    async def consulta(
        request: Request,
        authorization: str | None = Header(default=None),
        x_dispositivo: str = Header(default="esp32"),
        x_simular_falla: str | None = Header(default=None),
    ):
        try:
            autenticar(authorization)
        except HTTPException:
            asistente.registro.escribir({
                "turno": None, "dispositivo": x_dispositivo[:40], "estado": "rechazado",
                "error": "token inválido o ausente", "tiempos_ms": {},
                "cliente": request.client.host if request.client else None,
            })
            raise
        cuerpo = await request.body()
        if len(cuerpo) > MAX_BYTES_AUDIO:
            raise HTTPException(status_code=413, detail="Audio demasiado grande")

        simular = None
        if x_simular_falla and cfg.permitir_simulacion_fallas:
            simular = x_simular_falla.strip().lower()

        res = await asistente.procesar(cuerpo, x_dispositivo[:40], simular)
        log.info("turno=%s estado=%s tiempos=%s error=%s", res.turno, res.estado, res.tiempos_ms, res.error)
        cabeceras = {
            "X-Turno": res.turno,
            "X-Estado": res.estado,
            "X-Error": quote(res.error or ""),
            "X-Transcripcion": quote(res.transcripcion),
            "X-Respuesta": quote(res.respuesta),
            "X-Tiempos": quote(json.dumps(res.tiempos_ms)),
            "X-Proveedores": quote(json.dumps(res.proveedores)),
        }
        return Response(content=res.wav, media_type="audio/wav", status_code=res.codigo_http, headers=cabeceras)

    @app.delete("/api/historial")
    async def borrar_historial(
        authorization: str | None = Header(default=None), x_dispositivo: str = Header(default="esp32")
    ):
        autenticar(authorization)
        asistente.reiniciar_historial(x_dispositivo[:40])
        return {"estado": "ok"}

    @app.get("/api/registro")
    async def registro(n: int = 20, authorization: str | None = Header(default=None)):
        autenticar(authorization)
        return JSONResponse(asistente.registro.ultimos(min(max(n, 1), 200)))

    @app.get("/")
    async def inicio():
        return FileResponse(CARPETA_WEB / "index.html")

    app.mount("/web", StaticFiles(directory=CARPETA_WEB), name="web")
    return app
