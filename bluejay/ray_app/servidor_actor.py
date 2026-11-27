"""`ServidorActor`: envuelve un `ServidorBlueJay` (D2) como actor asíncrono de Ray.

Cada operación llama al núcleo (síncrono, puro) y encola en su `EntregadorActor` las
entregas que el núcleo devuelve, sin esperarlas (D4). La resolución de dependencias (D12)
corre en una tarea de fondo para no bloquear el `inbox` que la originó.
"""

from __future__ import annotations

import asyncio
from typing import Any

import ray
from ray.actor import ActorHandle

from bluejay.dominio.actividades import ActividadInvalida
from bluejay.dominio.modelos import Entrega, dominio_de
from bluejay.dominio.servidor import Resultado, ServidorBlueJay
from bluejay.ray_app.config import ConfigRay
from bluejay.ray_app.directorio import Directorio
from bluejay.ray_app.entregador import EntregadorActor
from bluejay.ray_app.excepciones import ERRORES_TRANSPORTE, ServidorNoDisponible

# Métodos de `ServidorBlueJay` que pueden invocarse por `llamar` (los de federación quedan
# fuera: tienen su propio método en el actor). Debe coincidir con `bluejay.web.backend.METODOS`;
# se duplica a propósito para que `ray_app` no dependa del paquete `web` (dirección de
# dependencia: web -> ray_app, nunca al revés).
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


@ray.remote(num_cpus=0)
class ServidorActor:
    def __init__(
        self, dominio: str, directorio: Directorio, entregador: ActorHandle, config: ConfigRay
    ) -> None:
        self._nucleo = ServidorBlueJay(dominio, limite_caracteres=config.limite_caracteres)
        self._directorio = directorio
        self._entregador = entregador
        self._config = config
        self._online = True
        self._tarea_dependencias: asyncio.Task[None] | None = None
        self._hay_dependencias_nuevas = asyncio.Event()
        self._intentos_dependencia: dict[str, int] = {}
        self._proximo_intento_dependencia: dict[str, float] = {}  # reloj de asyncio

    # --- Utilidades -------------------------------------------------------------------

    def _exigir_online(self) -> None:
        if not self._online:
            raise ServidorNoDisponible(f"{self._nucleo.dominio} está offline")

    async def _encolar_entregas(self, entregas: list[Entrega]) -> None:
        if entregas:
            await asyncio.gather(
                *(self._entregador.encolar.remote(e.destino, e.actividad) for e in entregas)
            )

    def _despertar_dependencias(self) -> None:
        self._hay_dependencias_nuevas.set()
        if self._tarea_dependencias is None or self._tarea_dependencias.done():
            self._tarea_dependencias = asyncio.create_task(self._bucle_dependencias())

    # --- API local (D2) ----------------------------------------------------------------

    async def llamar(self, metodo: str, *args: Any, **kwargs: Any) -> Any:
        if metodo not in METODOS:
            raise ValueError(f"Método no permitido: {metodo!r}")
        valor = getattr(self._nucleo, metodo)(*args, **kwargs)
        if isinstance(valor, Resultado):
            await self._encolar_entregas(valor.entregas)
            valor = valor.valor
        return valor

    # --- Federación: lo que llega de otros servidores ----------------------------------

    async def inbox(self, actividad: Any, dominio_remitente: str) -> None:
        self._exigir_online()
        entregas = self._nucleo.procesar(actividad, dominio_remitente)
        await self._encolar_entregas(entregas)
        if self._nucleo.dependencias_pendientes():
            self._despertar_dependencias()

    async def obtener_objeto(self, uri: str, dominio_solicitante: str) -> dict[str, Any] | None:
        self._exigir_online()
        return self._nucleo.servir_objeto(uri, dominio_solicitante)

    async def obtener_actor(self, uri: str) -> dict[str, Any] | None:
        self._exigir_online()
        return self._nucleo.servir_actor(uri)

    async def guardar_actor_remoto(self, persona: Any, origen: str) -> Any:
        return self._nucleo.guardar_actor_remoto(persona, origen)

    # --- Resolución de dependencias (D12) -----------------------------------------------

    async def _bucle_dependencias(self) -> None:
        """Pide cada original pendiente a su origen; los que fallan esperan con *backoff*
        (D12) sin frenar a los demás. Un `Announce` nuevo despierta el bucle antes de tiempo."""
        bucle = asyncio.get_running_loop()
        while True:
            pendientes = self._nucleo.dependencias_pendientes()
            self._olvidar_dependencias_resueltas(pendientes)
            if not pendientes:
                return
            self._hay_dependencias_nuevas.clear()
            for uri in pendientes:
                if self._proximo_intento_dependencia.get(uri, 0.0) <= bucle.time():
                    await self._resolver_dependencia(uri)
            if not self._nucleo.dependencias_pendientes():
                continue
            proximos = [
                self._proximo_intento_dependencia.get(uri, 0.0)
                for uri in self._nucleo.dependencias_pendientes()
            ]
            espera = max(min(proximos) - bucle.time(), 0.0)
            try:
                await asyncio.wait_for(self._hay_dependencias_nuevas.wait(), timeout=espera)
            except TimeoutError:
                pass

    def _olvidar_dependencias_resueltas(self, pendientes: list[str]) -> None:
        """Limpia los contadores de dependencias que ya no están pendientes (por ejemplo,
        porque llegó un `Undo` o un `Delete` mientras se esperaba el original)."""
        vigentes = set(pendientes)
        for registro in (self._intentos_dependencia, self._proximo_intento_dependencia):
            for uri in [u for u in registro if u not in vigentes]:
                del registro[uri]

    async def _resolver_dependencia(self, uri: str) -> None:
        origen = dominio_de(uri)
        try:
            actor = self._directorio.resolver(origen)
            objeto = await asyncio.wait_for(
                actor.obtener_objeto.remote(uri, self._nucleo.dominio),
                timeout=self._config.timeout,
            )
        except ERRORES_TRANSPORTE:
            self._directorio.invalidar(origen)
            intentos = self._intentos_dependencia.get(uri, 0) + 1
            if intentos >= self._config.maximo_intentos:
                self._nucleo.descartar_dependencia(uri)
            else:
                self._intentos_dependencia[uri] = intentos
                self._proximo_intento_dependencia[uri] = (
                    asyncio.get_running_loop().time() + self._config.backoff(intentos)
                )
            return
        # Al volver del `await` el núcleo decide con su estado actual (D17): si mientras
        # tanto llegó un `Undo` o un `Delete`, `recibir_objeto` descarta el original.
        if objeto is None:
            self._nucleo.descartar_dependencia(uri)
            return
        try:
            self._nucleo.recibir_objeto(objeto, origen)
        except ActividadInvalida:
            self._nucleo.descartar_dependencia(uri)

    # --- Disponibilidad y observabilidad -------------------------------------------------

    async def ping(self) -> bool:
        return True

    async def online(self) -> bool:
        return self._online

    async def set_online(self, online: bool) -> None:
        self._online = online
        if online:
            await self._entregador.reanudar.remote()
        else:
            await self._entregador.pausar.remote()

    async def estado(self) -> dict[str, Any]:
        return self._nucleo.estado()

    async def transporte(self) -> dict[str, Any]:
        pendientes, dead_letters = await asyncio.gather(
            self._entregador.pendientes.remote(), self._entregador.dead_letters.remote()
        )
        return {"pendientes": pendientes, "dead_letters": dead_letters}

    async def destruir(self) -> None:
        """Termina su `EntregadorActor`: nada externo lo referencia por nombre, así que
        quien crea el par con `levantar_servidores` es quien debe pedir que se libere."""
        ray.kill(self._entregador)


def levantar_servidores(
    dominios: tuple[str, ...], config: ConfigRay | None = None, namespace: str = "bluejay"
) -> dict[str, ActorHandle]:
    """Crea un `ServidorActor` y su `EntregadorActor` por cada dominio.

    Solo el `ServidorActor` se registra con nombre (D16): es lo único que otros
    servidores resuelven por dominio. Devuelve los handles ya listos (`ping` respondido),
    para evitar la carrera entre crear un actor con nombre y que el registro en el GCS
    esté disponible para quien lo resuelva después.
    """
    config = config or ConfigRay()
    directorio = Directorio(namespace)
    servidores: dict[str, ActorHandle] = {}
    for dominio in dominios:
        entregador = EntregadorActor.options(namespace=namespace).remote(
            dominio, directorio, config
        )
        servidor = ServidorActor.options(name=dominio, namespace=namespace).remote(
            dominio, directorio, entregador, config
        )
        servidores[dominio] = servidor
    ray.get([s.ping.remote() for s in servidores.values()])
    return servidores
