"""Etapa E.7: dejar de seguir con entregas en vuelo (D11; docs/fallos.md, 7).

Alpha está offline cuando Beto publica: el `Create` queda reintentándose en la cola de beta.
Mientras tanto Ana deja de seguir a Beto (operación local, funciona offline, D14) y su
`Undo(Follow)` queda en la cola pausada de alpha. Al reconectarse, las dos actividades se
cruzan en cualquier orden; en ninguno de los dos la publicación entra al inicio de Ana.
"""

import asyncio

import pytest

from tests.federacion.ayudas import BETO, config_paciente, esperar_hasta


@pytest.fixture
def config():
    return config_paciente()


def test_publicacion_en_vuelo_no_entra_despues_del_undo(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]
        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def ana_sigue_a_beto():
            return await alpha.llamar.remote("siguiendo", "ana") == [BETO]

        await esperar_hasta(ana_sigue_a_beto)

        await alpha.set_online.remote(False)
        await beta.llamar.remote("publicar", "beto", "en vuelo")

        async def create_en_vuelo():
            pendientes = (await beta.transporte.remote())["pendientes"]
            return len(pendientes) == 1 and pendientes[0]["intentos"] >= 1

        await esperar_hasta(create_en_vuelo)

        await alpha.llamar.remote("dejar_de_seguir", "ana", "@beto@beta.local")
        pendientes_alpha = (await alpha.transporte.remote())["pendientes"]
        assert [p["tipo"] for p in pendientes_alpha] == ["Undo"]

        await alpha.set_online.remote(True)

        async def ambas_colas_vacias():
            de_beta = await beta.transporte.remote()
            de_alpha = await alpha.transporte.remote()
            sin_seguidores = await beta.llamar.remote("seguidores", "beto") == []
            return de_beta["pendientes"] == de_alpha["pendientes"] == [] and sin_seguidores

        await esperar_hasta(ambas_colas_vacias, timeout=5.0)

        assert await alpha.llamar.remote("linea_inicio", "ana") == []
        for servidor in (alpha, beta):
            assert (await servidor.transporte.remote())["dead_letters"] == []

    asyncio.run(cuerpo())
