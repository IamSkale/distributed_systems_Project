"""Etapa E.8: una actividad inválida (*poison pill*) va a dead letter directo, sin
reintentos, y la cola de ese destino sigue avanzando (D6; docs/fallos.md, 8)."""

import asyncio

from tests.federacion.ayudas import ANA, esperar_hasta


def test_actividad_invalida_sin_reintentos(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")

        # "ghost" no existe en beta: el Follow será inválido. El Follow a Beto, válido,
        # queda detrás en la misma cola alpha -> beta.
        await alpha.llamar.remote("seguir", "ana", "@ghost@beta.local")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def la_cola_siguio():
            transporte = await alpha.transporte.remote()
            seguidores = await beta.llamar.remote("seguidores", "beto")
            # Beta registra a Ana antes de que su `inbox` responda: hasta entonces el Follow
            # sigue en la cabeza de la cola de alpha. Hay que esperar también a que salga.
            return (
                len(transporte["dead_letters"]) == 1
                and seguidores == [ANA]
                and transporte["pendientes"] == []
            )

        await esperar_hasta(la_cola_siguio)

        transporte = await alpha.transporte.remote()
        dead_letter = transporte["dead_letters"][0]
        assert dead_letter["destino"] == "beta.local"
        assert dead_letter["tipo"] == "Follow"
        assert not dead_letter["motivo"].startswith("máximo de intentos")  # sin reintentos

    asyncio.run(cuerpo())
