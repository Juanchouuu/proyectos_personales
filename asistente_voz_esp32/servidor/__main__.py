"""Arranca el servidor:  python -m servidor  [--puerto 8000] [--host 0.0.0.0]"""

import argparse

import uvicorn

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Servidor del asistente de voz ESP32-S3")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 permite que el ESP32 real se conecte por la red local")
    p.add_argument("--puerto", type=int, default=8000)
    a = p.parse_args()
    uvicorn.run("servidor.main:crear_app", factory=True, host=a.host, port=a.puerto)
