"""`EntregadorActor`: una cola FIFO acotada por destino, con reintentos y *dead letter* (D6).

Desacopla al `ServidorActor` de sus destinos (D4): `encolar` no espera nada. Por cada
destino hay un bucle propio (una `asyncio.Task`) que solo intenta la cabeza de su cola; el
resto de los destinos sigue avanzando aunque uno esté atascado.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

import ray

from bluejay.dominio.actividades import ActividadInvalida
from bluejay.ray_app.config import ConfigRay
from bluejay.ray_app.directorio import Directorio
from bluejay.ray_app.excepciones import ERRORES_TRANSPORTE


@dataclass(slots=True)
class _Pendiente:
    actividad: dict[str, Any]
    intentos: int = 0


@dataclass(frozen=True, slots=True)
class DeadLetter:
    destino: str
    actividad: dict[str, Any]
    motivo: str


@ray.remote(num_cpus=0)
class EntregadorActor:
    def __init__(self, dominio_propio: str, directorio: Directorio, config: ConfigRay) -> None:
        self._dominio_propio = dominio_propio
        self._directorio = directorio
        self._config = config
        self._colas: dict[str, deque[_Pendiente]] = {}
        self._tareas: dict[str, asyncio.Task[None]] = {}
        self._dead_letters: list[DeadLetter] = []
        self._en_marcha = asyncio.Event()
        self._en_marcha.set()

    # --- API ------------------------------------------------------------------------

    def iniciar(self) -> None:
        """No-op idempotente: los bucles de entrega arrancan solos al encolar."""

    def pausar(self) -> None:
        self._en_marcha.clear()

    def reanudar(self) -> None:
        self._en_marcha.set()

    def encolar(self, destino: str, actividad: dict[str, Any]) -> None:
        cola = self._colas.setdefault(destino, deque())
        if len(cola) >= self._config.tamano_cola:
            self._dead_letters.append(DeadLetter(destino, actividad, "cola llena"))
            return
        cola.append(_Pendiente(actividad))
        tarea = self._tareas.get(destino)
        if tarea is None or tarea.done():
            self._tareas[destino] = asyncio.create_task(self._bucle(destino))

    def pendientes(self) -> list[dict[str, Any]]:
        return [
            {
                "destino": destino,
                "tipo": pendiente.actividad["type"],
                "id": pendiente.actividad["id"],
                "intentos": pendiente.intentos,
            }
            for destino, cola in self._colas.items()
            for pendiente in cola
        ]

    def dead_letters(self) -> list[dict[str, Any]]:
        return [
            {
                "destino": d.destino,
                "tipo": d.actividad["type"],
                "id": d.actividad["id"],
                "motivo": d.motivo,
            }
            for d in self._dead_letters
        ]

    # --- Bucle de entrega por destino ------------------------------------------------

    async def _bucle(self, destino: str) -> None:
        cola = self._colas[destino]
        while cola:
            await self._en_marcha.wait()
            if not cola:
                break
            pendiente = cola[0]
            try:
                actor = self._directorio.resolver(destino)
                await asyncio.wait_for(
                    actor.inbox.remote(pendiente.actividad, self._dominio_propio),
                    timeout=self._config.timeout,
                )
            except ActividadInvalida as error:
                self._dead_letters.append(DeadLetter(destino, pendiente.actividad, str(error)))
                cola.popleft()
            except ERRORES_TRANSPORTE as error:
                self._directorio.invalidar(destino)
                pendiente.intentos += 1
                if pendiente.intentos >= self._config.maximo_intentos:
                    motivo = f"máximo de intentos agotado ({error.__class__.__name__})"
                    self._dead_letters.append(DeadLetter(destino, pendiente.actividad, motivo))
                    cola.popleft()
                else:
                    await asyncio.sleep(self._config.backoff(pendiente.intentos))
            except Exception as error:  # noqa: BLE001 - ver comentario
                # Cualquier otro error del receptor (p. ej., un fallo inesperado al procesar)
                # no se arregla reintentando: se trata como *poison pill* (D6, Conf. 4). Si no
                # se capturara, la tarea de este destino moriría con la actividad todavía en
                # la cabeza y la cola quedaría trabada para siempre.
                motivo = f"error inesperado ({error.__class__.__name__})"
                self._dead_letters.append(DeadLetter(destino, pendiente.actividad, motivo))
                cola.popleft()
            else:
                cola.popleft()
