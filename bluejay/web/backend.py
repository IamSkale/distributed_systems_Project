"""El *backend* de la API web: a qué se conectan las rutas.

Las rutas no saben si debajo hay núcleos en el mismo proceso o actores de Ray: solo ven el
protocolo `Backend`, cuyos métodos son asíncronos y llaman a los métodos de
`ServidorBlueJay` por nombre. Hay dos implementaciones con las mismas firmas, y ni las
rutas ni el frontend saben cuál tienen debajo: es la misma separación de dominio y
transporte de D2 (Conf. 2), un nivel más arriba.

- `BackendLocal` usa `RedLocal`: entrega síncrona, sin *backoff*, sin Ray.
- `BackendRay` hace `await actor.<metodo>.remote(...)` sobre un `ServidorActor` por dominio
  (Etapa D): entrega asíncrona con reintentos, colas acotadas y *dead letter* (D4, D6).
  Se elige con `BLUEJAY_BACKEND=ray` (ver `bluejay/web/app.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import ray
from ray.actor import ActorHandle
from ray.exceptions import RayActorError

from bluejay.dominio.actividades import ActividadInvalida
from bluejay.dominio.modelos import dominio_de
from bluejay.dominio.servidor import Resultado
from bluejay.ray_app.config import ConfigRay
from bluejay.ray_app.excepciones import ServidorNoDisponible
from bluejay.ray_app.servidor_actor import levantar_servidores
from bluejay.transporte_local import RedLocal

DOMINIOS_DEMO = ("alpha.local", "beta.local", "gamma.local")

# Métodos de `ServidorBlueJay` que la API puede invocar (los de federación quedan fuera).
METODOS = frozenset(
    {
        "registrar_usuario",
        "usuarios",
        "perfil",
        "nombres",
        "publicar",
        "eliminar",
        "republicar",
        "deshacer_republicacion",
        "seguir",
        "dejar_de_seguir",
        "solicitudes",
        "seguidores",
        "siguiendo",
        "aceptar",
        "rechazar",
        "linea_inicio",
        "linea_perfil",
        "estado",
    }
)


class ServidorDesconocido(LookupError):
    """No hay ningún servidor con ese dominio."""


class Backend(Protocol):
    async def dominios(self) -> list[str]: ...

    async def llamar(self, dominio: str, metodo: str, *args: Any, **kwargs: Any) -> Any:
        """Ejecuta `ServidorBlueJay.<metodo>` en `dominio`, encola sus entregas y devuelve
        el valor (no el `Resultado`)."""

    async def nombres(self, dominio: str, uris: list[str]) -> dict[str, str | None]:
        """Como `ServidorBlueJay.nombres`, pidiendo al origen los actores que no conoce."""

    async def online(self, dominio: str) -> bool: ...

    async def set_online(self, dominio: str, online: bool) -> None:
        """Modo *offline* (D14): las operaciones locales siguen; la federación se detiene."""

    async def transporte(self, dominio: str) -> dict[str, Any]:
        """Entregas pendientes y *dead letters* que salen de `dominio` (observabilidad)."""


class BackendLocal:
    """Núcleos en el mismo proceso conectados con `RedLocal`."""

    def __init__(self, dominios: tuple[str, ...] = DOMINIOS_DEMO) -> None:
        self.red = RedLocal(*dominios)

    def _exigir(self, dominio: str) -> None:
        if dominio not in self.red:
            raise ServidorDesconocido(f"No existe el servidor {dominio!r}")

    async def dominios(self) -> list[str]:
        return list(self.red.servidores)

    async def llamar(self, dominio: str, metodo: str, *args: Any, **kwargs: Any) -> Any:
        self._exigir(dominio)
        if metodo not in METODOS:
            raise ValueError(f"Método no permitido: {metodo!r}")
        valor = getattr(self.red[dominio], metodo)(*args, **kwargs)
        if isinstance(valor, Resultado):
            valor = self.red.hacer(dominio, valor)
        return valor

    async def nombres(self, dominio: str, uris: list[str]) -> dict[str, str | None]:
        self._exigir(dominio)
        servidor = self.red[dominio]
        nombres = servidor.nombres(uris)
        for uri, nombre in nombres.items():
            origen = dominio_de(uri)
            if nombre is not None or origen not in self.red:
                continue
            if dominio in self.red.desconectados or origen in self.red.desconectados:
                continue
            # obtener_actor: caché de actores remotos (Etapa D, tarea 6).
            persona = self.red[origen].servir_actor(uri)
            if persona is not None:
                try:
                    nombres[uri] = servidor.guardar_actor_remoto(persona, origen).nombre
                except ActividadInvalida:
                    pass
        return nombres

    async def online(self, dominio: str) -> bool:
        self._exigir(dominio)
        return dominio not in self.red.desconectados

    async def set_online(self, dominio: str, online: bool) -> None:
        self._exigir(dominio)
        if online:
            self.red.reconectar(dominio)
        else:
            self.red.desconectar(dominio)

    async def transporte(self, dominio: str) -> dict[str, Any]:
        self._exigir(dominio)
        return {
            "pendientes": [
                {"destino": e.destino, "tipo": e.actividad["type"], "id": e.id_actividad}
                for _, e in self.red.pendientes(dominio)
            ],
            "dead_letters": [
                {
                    "destino": d.entrega.destino,
                    "tipo": d.entrega.actividad["type"],
                    "id": d.entrega.id_actividad,
                    "motivo": d.motivo,
                }
                for d in self.red.dead_letters
                if d.remitente == dominio
            ],
        }


class BackendRay:
    """`ServidorActor` de Ray, uno por dominio (Etapa D). Mismas firmas que `BackendLocal`;
    las rutas de la API no saben cuál de los dos tienen debajo (D2, un nivel más arriba)."""

    def __init__(
        self,
        dominios: tuple[str, ...] = DOMINIOS_DEMO,
        namespace: str = "bluejay",
        config: ConfigRay | None = None,
    ) -> None:
        self._dominios = dominios
        self._config = config or ConfigRay()
        self._actores: dict[str, ActorHandle] = levantar_servidores(
            dominios, self._config, namespace
        )

    def _exigir(self, dominio: str) -> ActorHandle:
        try:
            return self._actores[dominio]
        except KeyError:
            raise ServidorDesconocido(f"No existe el servidor {dominio!r}") from None

    async def _esperar(self, objeto_ref: Any) -> Any:
        try:
            return await asyncio.wait_for(objeto_ref, timeout=self._config.timeout)
        except RayActorError as error:
            raise ServidorDesconocido(f"El servidor no responde: {error}") from error

    async def dominios(self) -> list[str]:
        return list(self._dominios)

    async def llamar(self, dominio: str, metodo: str, *args: Any, **kwargs: Any) -> Any:
        actor = self._exigir(dominio)
        return await self._esperar(actor.llamar.remote(metodo, *args, **kwargs))

    async def nombres(self, dominio: str, uris: list[str]) -> dict[str, str | None]:
        actor = self._exigir(dominio)
        nombres = await self._esperar(actor.llamar.remote("nombres", uris))
        for uri, nombre in nombres.items():
            origen = dominio_de(uri)
            if nombre is not None or origen not in self._actores:
                continue
            # obtener_actor: caché de actores remotos (Etapa D, tarea 6).
            try:
                persona = await self._esperar(self._actores[origen].obtener_actor.remote(uri))
            except (ServidorNoDisponible, ServidorDesconocido):
                continue
            if persona is None:
                continue
            try:
                actor_remoto = await self._esperar(
                    actor.guardar_actor_remoto.remote(persona, origen)
                )
            except ActividadInvalida:
                continue
            nombres[uri] = actor_remoto.nombre
        return nombres

    async def online(self, dominio: str) -> bool:
        actor = self._exigir(dominio)
        return await self._esperar(actor.online.remote())

    async def set_online(self, dominio: str, online: bool) -> None:
        actor = self._exigir(dominio)
        await self._esperar(actor.set_online.remote(online))

    async def transporte(self, dominio: str) -> dict[str, Any]:
        actor = self._exigir(dominio)
        return await self._esperar(actor.transporte.remote())

    async def cerrar(self) -> None:
        """Libera los `ServidorActor` y sus `EntregadorActor` (fuera del protocolo `Backend`:
        solo lo usa quien creó el backend, p. ej., una prueba al terminar)."""
        for actor in self._actores.values():
            try:
                await self._esperar(actor.destruir.remote())
            except (ServidorDesconocido, TimeoutError):
                pass
            ray.kill(actor)
        self._actores.clear()


async def _esperar_propagacion(
    obtener: Callable[[], Awaitable[list[Any]]], minimo: int = 1
) -> None:
    """Con `BackendLocal` la entrega ya está resuelta cuando `llamar` vuelve (síncrono);
    con `BackendRay` viaja por el `EntregadorActor` (D4, asíncrono), así que el guion de
    la demo tiene que esperarla antes de depender de su efecto (p. ej., antes de
    `aceptar` una solicitud o de publicar algo que otro dominio debe recibir)."""
    for _ in range(100):
        if len(await obtener()) >= minimo:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("sembrar: una entrega no llegó a tiempo")


async def sembrar(backend: Backend) -> None:
    """Datos de ejemplo: el comienzo del guion de la demo (plan_entrega_1.md, sección 5)."""
    a, b, g = DOMINIOS_DEMO
    await backend.llamar(a, "registrar_usuario", "ana", "Ana")
    await backend.llamar(a, "registrar_usuario", "dani", "Dani")
    await backend.llamar(b, "registrar_usuario", "beto", "Beto", protegida=True)
    await backend.llamar(g, "registrar_usuario", "caro", "Caro")

    await backend.llamar(a, "seguir", "ana", "@beto@beta.local")
    await _esperar_propagacion(lambda: backend.llamar(b, "solicitudes", "beto"))
    await backend.llamar(b, "aceptar", "beto", "https://alpha.local/users/ana")

    await backend.llamar(g, "seguir", "caro", "@ana@alpha.local")
    await backend.llamar(a, "seguir", "dani", "@ana@alpha.local")
    await _esperar_propagacion(lambda: backend.llamar(a, "seguidores", "ana"), minimo=2)

    hola = await backend.llamar(b, "publicar", "beto", "Hola desde beta 👋")
    await backend.llamar(b, "publicar", "beto", "Esto solo lo ven mis seguidores", "followers")
    # Ana solo puede republicar lo que alpha ya recibió. Las dos publicaciones de Beto
    # viajan por la misma cola beta -> alpha (FIFO por destino, D6): con ver dos basta.
    await _esperar_propagacion(lambda: backend.llamar(a, "linea_inicio", "ana"), minimo=2)
    await backend.llamar(a, "publicar", "ana", "Probando Blue Jay desde alpha")
    await backend.llamar(a, "republicar", "ana", hola.uri)
