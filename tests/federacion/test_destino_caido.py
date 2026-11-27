"""Etapa E.1: servidor destino caído (D6, D14; docs/fallos.md, 1).

Ana (alpha) y Caro (gamma) siguen a Beto (beta). Gamma se desconecta y Beto publica: alpha
la recibe sin demora (los destinos no dependen entre sí) y la entrega hacia gamma queda en
la cola de beta, reintentándose. Al reconectarse, gamma converge sin intervención.
"""

import asyncio

import pytest

from tests.federacion.ayudas import BETO, config_paciente, esperar_hasta, uris


@pytest.fixture
def config():
    return config_paciente()


def test_destino_caido_converge_al_reconectar(crear_servidores):
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
        await gamma.llamar.remote("seguir", "caro", "@beto@beta.local")

        async def ambos_aceptados():
            # Además, los dos Accept tienen que haber salido de la cola de beta: si no, el
            # de gamma también quedaría pendiente y la cuenta de abajo no cerraría.
            seguidores = await beta.llamar.remote("seguidores", "beto")
            transporte = await beta.transporte.remote()
            siguiendo = await gamma.llamar.remote("siguiendo", "caro")
            return len(seguidores) == 2 and transporte["pendientes"] == [] and siguiendo == [BETO]

        await esperar_hasta(ambos_aceptados)

        await gamma.set_online.remote(False)
        hola = await beta.llamar.remote("publicar", "beto", "Hola a todos")

        # El destino que está vivo no espera al caído (cola por destino, D6).
        async def alpha_la_tiene():
            return uris(await alpha.llamar.remote("linea_inicio", "ana")) == [hola.uri]

        await esperar_hasta(alpha_la_tiene)

        async def gamma_se_reintenta():
            pendientes = (await beta.transporte.remote())["pendientes"]
            return len(pendientes) == 1 and pendientes[0]["intentos"] >= 1

        await esperar_hasta(gamma_se_reintenta)
        pendiente = (await beta.transporte.remote())["pendientes"][0]
        assert pendiente["destino"] == "gamma.local"
        assert pendiente["tipo"] == "Create"

        # Mientras tanto, Caro no la ve (su servidor sigue respondiendo a lo local, D14).
        assert await gamma.llamar.remote("linea_inicio", "caro") == []

        await gamma.set_online.remote(True)

        async def gamma_convergio():
            return uris(await gamma.llamar.remote("linea_inicio", "caro")) == [hola.uri]

        await esperar_hasta(gamma_convergio)
        transporte = await beta.transporte.remote()
        assert transporte["pendientes"] == []
        assert transporte["dead_letters"] == []

    asyncio.run(cuerpo())
