"""API web de Blue Jay (JSON) y servidor del frontend.

Contrato de las rutas: `docs/api.md`. Arranque:

    uv run python -m bluejay.web          # http://127.0.0.1:8000  (docs en /docs)

Todas las rutas de un servidor llevan su dominio: `/api/{dominio}/...`. En la Entrega 1
no hay inicio de sesión: el frontend elige servidor y usuario, y las lecturas reciben
`visto_por` para aplicar la visibilidad (docs/visibilidad.md, sección 1).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bluejay.dominio.actividades import fecha_a_texto
from bluejay.dominio.lineas import ElementoLinea
from bluejay.dominio.modelos import (
    Publicacion,
    Republicacion,
    Visibilidad,
    handle_desde_uri,
    uri_desde_handle,
)
from bluejay.dominio.servidor import ErrorOperacion, NoEncontrado
from bluejay.web.backend import Backend, BackendLocal, ServidorDesconocido, sembrar

RAIZ = Path(__file__).resolve().parents[2]


# --- Cuerpos de las peticiones -------------------------------------------------------


class NuevoUsuario(BaseModel):
    username: str
    nombre: str
    protegida: bool = False


class NuevaPublicacion(BaseModel):
    texto: str
    visibilidad: Visibilidad = Visibilidad.PUBLICA


class RefPublicacion(BaseModel):
    uri: str


class RefUsuario(BaseModel):
    handle: str = Field(description="@usuario@servidor (también vale sin la @ inicial o una URI)")


class Conexion(BaseModel):
    online: bool


# --- Conversión a JSON ---------------------------------------------------------------


def a_uri(handle_o_uri: str) -> str:
    """Acepta `@ana@alpha.local`, `ana@alpha.local` o `https://alpha.local/users/ana`."""
    if handle_o_uri.startswith(("http://", "https://")):
        handle_desde_uri(handle_o_uri)  # valida
        return handle_o_uri
    return uri_desde_handle(handle_o_uri)


def a_handle(handle_o_uri: str) -> str:
    return handle_desde_uri(a_uri(handle_o_uri))


def json_actor(uri: str, nombres: dict[str, str | None]) -> dict[str, Any]:
    return {"uri": uri, "handle": handle_desde_uri(uri), "nombre": nombres.get(uri)}


def json_publicacion(p: Publicacion, nombres: dict[str, str | None]) -> dict[str, Any]:
    return {
        "uri": p.uri,
        "autor": json_actor(p.autor, nombres),
        "contenido": p.contenido,
        "visibilidad": str(p.visibilidad),
        "publicada": fecha_a_texto(p.publicada),
        "republicable": p.es_republicable,
    }


def json_republicacion(r: Republicacion, nombres: dict[str, str | None]) -> dict[str, Any]:
    return {
        "uri": r.uri,
        "actor": json_actor(r.actor, nombres),
        "publicada": fecha_a_texto(r.publicada),
    }


def json_elemento(e: ElementoLinea, nombres: dict[str, str | None]) -> dict[str, Any]:
    return {
        **json_publicacion(e.publicacion, nombres),
        "republicacion": None
        if e.republicacion is None
        else json_republicacion(e.republicacion, nombres),
    }


async def json_linea(
    backend: Backend, dominio: str, elementos: list[ElementoLinea]
) -> list[dict[str, Any]]:
    uris = {e.publicacion.autor for e in elementos} | {
        e.republicacion.actor for e in elementos if e.republicacion
    }
    nombres = await backend.nombres(dominio, sorted(uris))
    return [json_elemento(e, nombres) for e in elementos]


async def json_actores(backend: Backend, dominio: str, uris: list[str]) -> list[dict[str, Any]]:
    nombres = await backend.nombres(dominio, uris)
    return [json_actor(uri, nombres) for uri in uris]


# --- Aplicación -----------------------------------------------------------------------


def crear_app(backend: Backend | None = None, semilla: bool = True) -> FastAPI:
    backend = backend if backend is not None else BackendLocal()

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI):
        if semilla:
            await sembrar(backend)
        yield

    app = FastAPI(
        title="Blue Jay",
        description="Red federada de micropublicaciones. Contrato: docs/api.md",
        lifespan=ciclo_de_vida,
    )
    app.state.backend = backend
    # Permite abrir el frontend desde otro servidor de desarrollo (p. ej., Live Server).
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    def error(estado: int):
        async def manejador(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=estado, content={"detail": str(exc).strip("'\"")})

        return manejador

    app.add_exception_handler(NoEncontrado, error(404))
    app.add_exception_handler(ServidorDesconocido, error(404))
    app.add_exception_handler(ErrorOperacion, error(400))
    app.add_exception_handler(ValueError, error(400))

    # --- Servidores (administración y modo offline, D14) ---

    @app.get("/api/servidores", tags=["servidores"])
    async def listar_servidores() -> list[dict[str, Any]]:
        return [{"dominio": d, "online": await backend.online(d)} for d in await backend.dominios()]

    @app.get("/api/servidores/{dominio}", tags=["servidores"])
    async def ver_servidor(dominio: str) -> dict[str, Any]:
        return {
            "dominio": dominio,
            "online": await backend.online(dominio),
            "estado": await backend.llamar(dominio, "estado"),
            **await backend.transporte(dominio),
        }

    @app.put("/api/servidores/{dominio}/conexion", tags=["servidores"])
    async def cambiar_conexion(dominio: str, cuerpo: Conexion) -> dict[str, Any]:
        await backend.set_online(dominio, cuerpo.online)
        return {"dominio": dominio, "online": await backend.online(dominio)}

    # --- Usuarios ---

    @app.get("/api/{dominio}/usuarios", tags=["usuarios"])
    async def listar_usuarios(dominio: str, visto_por: str | None = None) -> list[dict]:
        return await backend.llamar(dominio, "usuarios", visto_por)

    @app.post("/api/{dominio}/usuarios", status_code=201, tags=["usuarios"])
    async def registrar(dominio: str, cuerpo: NuevoUsuario) -> dict[str, Any]:
        usuario = await backend.llamar(
            dominio, "registrar_usuario", cuerpo.username, cuerpo.nombre, cuerpo.protegida
        )
        return await backend.llamar(dominio, "perfil", usuario.handle)

    @app.get("/api/{dominio}/perfiles/{handle}", tags=["usuarios"])
    async def ver_perfil(dominio: str, handle: str, visto_por: str | None = None) -> dict:
        handle = a_handle(handle)
        datos = await backend.llamar(dominio, "perfil", handle, visto_por)
        if datos["nombre"] is None:
            datos["nombre"] = (await backend.nombres(dominio, [datos["uri"]]))[datos["uri"]]
        return datos

    # --- Líneas de tiempo ---

    @app.get("/api/{dominio}/usuarios/{username}/inicio", tags=["líneas de tiempo"])
    async def inicio(dominio: str, username: str, limite: int = 20) -> list[dict]:
        elementos = await backend.llamar(dominio, "linea_inicio", username, limite)
        return await json_linea(backend, dominio, elementos)

    @app.get("/api/{dominio}/perfiles/{handle}/publicaciones", tags=["líneas de tiempo"])
    async def publicaciones_de_perfil(
        dominio: str, handle: str, visto_por: str | None = None, limite: int = 20
    ) -> list[dict]:
        elementos = await backend.llamar(
            dominio, "linea_perfil", a_handle(handle), visto_por, limite
        )
        return await json_linea(backend, dominio, elementos)

    # --- Publicaciones ---

    @app.post(
        "/api/{dominio}/usuarios/{username}/publicaciones", status_code=201, tags=["publicaciones"]
    )
    async def publicar(dominio: str, username: str, cuerpo: NuevaPublicacion) -> dict:
        publicacion = await backend.llamar(
            dominio, "publicar", username, cuerpo.texto, cuerpo.visibilidad
        )
        nombres = await backend.nombres(dominio, [publicacion.autor])
        return json_elemento(ElementoLinea(publicacion), nombres)

    @app.post("/api/{dominio}/usuarios/{username}/eliminar", tags=["publicaciones"])
    async def eliminar(dominio: str, username: str, cuerpo: RefPublicacion) -> dict:
        await backend.llamar(dominio, "eliminar", username, cuerpo.uri)
        return {"ok": True}

    @app.post("/api/{dominio}/usuarios/{username}/republicar", tags=["publicaciones"])
    async def republicar(dominio: str, username: str, cuerpo: RefPublicacion) -> dict:
        republicacion = await backend.llamar(dominio, "republicar", username, cuerpo.uri)
        nombres = await backend.nombres(dominio, [republicacion.actor])
        return json_republicacion(republicacion, nombres)

    @app.post("/api/{dominio}/usuarios/{username}/deshacer-republicacion", tags=["publicaciones"])
    async def deshacer_republicacion(dominio: str, username: str, cuerpo: RefPublicacion) -> dict:
        await backend.llamar(dominio, "deshacer_republicacion", username, cuerpo.uri)
        return {"ok": True}

    # --- Seguimiento ---

    @app.post("/api/{dominio}/usuarios/{username}/seguir", tags=["seguimiento"])
    async def seguir(dominio: str, username: str, cuerpo: RefUsuario) -> dict:
        seguimiento = await backend.llamar(dominio, "seguir", username, a_handle(cuerpo.handle))
        return {"seguido": seguimiento.seguido, "estado": str(seguimiento.estado)}

    @app.post("/api/{dominio}/usuarios/{username}/dejar-de-seguir", tags=["seguimiento"])
    async def dejar_de_seguir(dominio: str, username: str, cuerpo: RefUsuario) -> dict:
        await backend.llamar(dominio, "dejar_de_seguir", username, a_handle(cuerpo.handle))
        return {"ok": True}

    @app.get("/api/{dominio}/usuarios/{username}/solicitudes", tags=["seguimiento"])
    async def solicitudes(dominio: str, username: str) -> list[dict]:
        uris = await backend.llamar(dominio, "solicitudes", username)
        return await json_actores(backend, dominio, uris)

    @app.post("/api/{dominio}/usuarios/{username}/aceptar", tags=["seguimiento"])
    async def aceptar(dominio: str, username: str, cuerpo: RefUsuario) -> dict:
        await backend.llamar(dominio, "aceptar", username, a_uri(cuerpo.handle))
        return {"ok": True}

    @app.post("/api/{dominio}/usuarios/{username}/rechazar", tags=["seguimiento"])
    async def rechazar(dominio: str, username: str, cuerpo: RefUsuario) -> dict:
        await backend.llamar(dominio, "rechazar", username, a_uri(cuerpo.handle))
        return {"ok": True}

    @app.get("/api/{dominio}/usuarios/{username}/seguidores", tags=["seguimiento"])
    async def seguidores(dominio: str, username: str) -> list[dict]:
        uris = await backend.llamar(dominio, "seguidores", username)
        return await json_actores(backend, dominio, uris)

    @app.get("/api/{dominio}/usuarios/{username}/siguiendo", tags=["seguimiento"])
    async def siguiendo(dominio: str, username: str) -> list[dict]:
        uris = await backend.llamar(dominio, "siguiendo", username)
        return await json_actores(backend, dominio, uris)

    # --- Frontend ---

    app.mount("/static", StaticFiles(directory=RAIZ / "static"), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(RAIZ / "templates" / "index.html")

    return app


app = crear_app()
