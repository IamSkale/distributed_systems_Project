"""El *backend* de la API web: a qué se conectan las rutas.

Las rutas no saben si debajo hay núcleos en el mismo proceso o actores de Ray: solo ven el
protocolo `Backend`, cuyos métodos son asíncronos y llaman a los métodos de
`ServidorBlueJay` por nombre. Así, cuando exista la capa de Ray (Etapa D), un `BackendRay`
hará `await actor.<metodo>.remote(...)` con las mismas firmas y ni las rutas ni el frontend
cambian. Es la misma separación de dominio y transporte de D2 (Conf. 2), un nivel más arriba.

`BackendLocal` usa `RedLocal`: entrega síncrona, sin *backoff*. Sirve para adelantar el
frontend; la semántica de fallos completa (reintentos, colas acotadas) llega con Ray.
"""

from __future__ import annotations

from typing import Any, Protocol

from bluejay.dominio.actividades import ActividadInvalida
from bluejay.dominio.modelos import dominio_de
from bluejay.dominio.servidor import Resultado
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


async def sembrar(backend: Backend) -> None:
    """Datos de ejemplo: el comienzo del guion de la demo (plan_entrega_1.md, sección 5)."""
    a, b, g = DOMINIOS_DEMO
    await backend.llamar(a, "registrar_usuario", "ana", "Ana")
    await backend.llamar(a, "registrar_usuario", "dani", "Dani")
    await backend.llamar(b, "registrar_usuario", "beto", "Beto", protegida=True)
    await backend.llamar(g, "registrar_usuario", "caro", "Caro")

    await backend.llamar(a, "seguir", "ana", "@beto@beta.local")
    await backend.llamar(b, "aceptar", "beto", "https://alpha.local/users/ana")
    await backend.llamar(g, "seguir", "caro", "@ana@alpha.local")
    await backend.llamar(a, "seguir", "dani", "@ana@alpha.local")

    hola = await backend.llamar(b, "publicar", "beto", "Hola desde beta 👋")
    await backend.llamar(b, "publicar", "beto", "Esto solo lo ven mis seguidores", "followers")
    await backend.llamar(a, "publicar", "ana", "Probando Blue Jay desde alpha")
    await backend.llamar(a, "republicar", "ana", hola.uri)
