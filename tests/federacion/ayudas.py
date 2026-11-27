"""Helpers de las pruebas de federación: espera activa (ningún test usa `sleep` fijo) y
escenarios que se repiten entre pruebas."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from bluejay.ray_app.config import ConfigRay, config_pruebas

ANA = "https://alpha.local/users/ana"
BETO = "https://beta.local/users/beto"
CARO = "https://gamma.local/users/caro"


def config_paciente() -> ConfigRay:
    """Como `config_pruebas`, pero el entregador tarda ~3 s en rendirse (esperas de 0,1,
    0,2, 0,4, 0,8 y 1,6 s): da tiempo a reconectar un servidor antes de la *dead letter*.
    Con `config_pruebas` los reintentos se agotan en unos 60 ms y una prueba que reconecta
    "a tiempo" dependería de la velocidad de la máquina."""
    return replace(config_pruebas(), intervalo_base=0.1, maximo_intentos=6)


def uris(linea: list[Any]) -> list[str]:
    return [elemento.publicacion.uri for elemento in linea]


async def esperar_hasta(
    condicion: Callable[[], bool | Awaitable[bool]],
    timeout: float = 3.0,
    intervalo: float = 0.02,
) -> None:
    inicio = time.monotonic()
    while True:
        resultado = condicion()
        if asyncio.iscoroutine(resultado):
            resultado = await resultado
        if resultado:
            return
        if time.monotonic() - inicio >= timeout:
            raise AssertionError(f"la condición no se cumplió en {timeout}s")
        await asyncio.sleep(intervalo)


async def armar_cadena(servidores) -> Any:
    """Ana (alpha) sigue a Beto (beta) y Caro (gamma) sigue a Ana; Beto publica y Ana lo
    republica. Gamma nunca recibió el `Create`: tiene que pedir el original a beta (D12).

    Devuelve la publicación de Beto, ya visible en el inicio de Ana y en el de Caro.
    """
    alpha, beta, gamma = (
        servidores["alpha.local"],
        servidores["beta.local"],
        servidores["gamma.local"],
    )
    await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
    await beta.llamar.remote("registrar_usuario", "beto", "Beto")
    await gamma.llamar.remote("registrar_usuario", "caro", "Caro")

    await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")
    await gamma.llamar.remote("seguir", "caro", "@ana@alpha.local")

    async def follows_aceptados():
        # Quien decide el fan-out es el servidor del autor (beta para beto, alpha para
        # ana): hay que esperar a que procese el Follow, no al estado local de quien sigue.
        seguidores_beto = await beta.llamar.remote("seguidores", "beto")
        seguidores_ana = await alpha.llamar.remote("seguidores", "ana")
        return len(seguidores_beto) == 1 and len(seguidores_ana) == 1

    await esperar_hasta(follows_aceptados)

    hola = await beta.llamar.remote("publicar", "beto", "Hola desde beta")

    async def alpha_la_tiene():
        return len(await alpha.llamar.remote("linea_inicio", "ana")) == 1

    await esperar_hasta(alpha_la_tiene)

    await alpha.llamar.remote("republicar", "ana", hola.uri)

    async def gamma_resuelve_dependencia():
        linea = await gamma.llamar.remote("linea_inicio", "caro")
        return len(linea) == 1 and linea[0].publicacion.uri == hola.uri

    await esperar_hasta(gamma_resuelve_dependencia, timeout=5.0)
    return hola
