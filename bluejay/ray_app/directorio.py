"""Resuelve un dominio a su `ServidorActor` (D16): descubrimiento por registro de Ray.

`ray.get_actor` es una consulta al GCS, no una llamada remota al actor: no bloquea en su
ejecución y es seguro llamarla desde dentro de otro actor (no es el `ray.get()` prohibido
sobre un `ObjectRef` de una tarea en curso).
"""

from __future__ import annotations

import ray
from ray.actor import ActorHandle


class ServidorDesconocido(LookupError):
    """No hay ningún `ServidorActor` registrado con ese dominio en este namespace."""


class Directorio:
    """Caché de handles por dominio, con invalidación tras un `RayActorError` (D16)."""

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._cache: dict[str, ActorHandle] = {}

    def resolver(self, dominio: str) -> ActorHandle:
        handle = self._cache.get(dominio)
        if handle is not None:
            return handle
        try:
            handle = ray.get_actor(dominio, namespace=self._namespace)
        except ValueError:
            raise ServidorDesconocido(f"No existe el servidor {dominio!r}") from None
        self._cache[dominio] = handle
        return handle

    def invalidar(self, dominio: str) -> None:
        self._cache.pop(dominio, None)
