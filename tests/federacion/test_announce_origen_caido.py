"""Etapa E.5: `Announce` de una publicación desconocida con el origen caído (D12;
docs/fallos.md, 5).

Caro (gamma) sigue a Ana (alpha), que republica una publicación de Beto (beta) mientras
beta está offline. Gamma acepta el `Announce`, lo guarda en pendientes y reintenta pedir el
original con *backoff*; la republicación no se muestra hasta que el original llega. Mientras
tanto la cola de alpha hacia gamma sigue fluyendo: lo que Ana publica llega a Caro.
"""

import asyncio

import pytest

from tests.federacion.ayudas import ANA, BETO, config_paciente, esperar_hasta, uris


@pytest.fixture
def config():
    # Gamma reintenta pedir el original con el mismo backoff que el entregador: hay que
    # reconectar a beta antes de que se rinda.
    return config_paciente()


def test_announce_espera_al_original_sin_bloquear_la_cola(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local", "gamma.local")
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
            siguiendo_ana = await alpha.llamar.remote("siguiendo", "ana")
            siguiendo_caro = await gamma.llamar.remote("siguiendo", "caro")
            return siguiendo_ana == [BETO] and siguiendo_caro == [ANA]

        await esperar_hasta(follows_aceptados)

        hola = await beta.llamar.remote("publicar", "beto", "Hola desde beta")

        async def alpha_la_tiene():
            return uris(await alpha.llamar.remote("linea_inicio", "ana")) == [hola.uri]

        await esperar_hasta(alpha_la_tiene)

        await beta.set_online.remote(False)
        await alpha.llamar.remote("republicar", "ana", hola.uri)

        async def gamma_espera_el_original():
            return (await gamma.estado.remote())["dependencias_pendientes"] == 1

        await esperar_hasta(gamma_espera_el_original)
        assert await gamma.llamar.remote("linea_inicio", "caro") == []

        # La dependencia pendiente no frena la cola alpha -> gamma.
        propia = await alpha.llamar.remote("publicar", "ana", "Mientras tanto")

        async def caro_ve_la_propia():
            return uris(await gamma.llamar.remote("linea_inicio", "caro")) == [propia.uri]

        await esperar_hasta(caro_ve_la_propia)
        assert (await gamma.estado.remote())["dependencias_pendientes"] == 1

        await beta.set_online.remote(True)

        async def republicacion_visible():
            linea = await gamma.llamar.remote("linea_inicio", "caro")
            return hola.uri in uris(linea)

        await esperar_hasta(republicacion_visible, timeout=5.0)
        linea = await gamma.llamar.remote("linea_inicio", "caro")
        republicada = next(e for e in linea if e.publicacion.uri == hola.uri)
        assert republicada.republicacion is not None
        assert republicada.republicacion.actor == ANA
        assert (await gamma.estado.remote())["dependencias_pendientes"] == 0

    asyncio.run(cuerpo())
