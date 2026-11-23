"""`uv run python -m bluejay.web [--port 8000] [--reload]`"""

import argparse

import uvicorn

parser = argparse.ArgumentParser(description="API web y frontend de Blue Jay")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--reload", action="store_true", help="reiniciar al cambiar el código")
args = parser.parse_args()

uvicorn.run("bluejay.web.app:app", host=args.host, port=args.port, reload=args.reload)
