"""Flujo 6: dejar de seguir de forma remota (`Undo(Follow)`, D11).

Dani (alpha) también sigue a Beto, así que beta sigue entregando a alpha después del
`Undo(Follow)` de Ana (*shared inbox*, D5). Eso permite comprobar, sin esperar a que "no
pase nada", que una publicación posterior llega a alpha pero no entra al inicio de Ana.
"""

import asyncio

from tests.federacion.ayudas import esperar_hasta

ANA = "https://alpha.local/users/ana"
DANI = "https://alpha.local/users/dani"


def test_dejar_de_seguir_remoto(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await alpha.llamar.remote("registrar_usuario", "dani", "Dani")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")
        await alpha.llamar.remote("seguir", "dani", "@beto@beta.local")

        async def beta_acepto_ambos():
            return len(await beta.llamar.remote("seguidores", "beto")) == 2

        await esperar_hasta(beta_acepto_ambos)

        await beta.llamar.remote("publicar", "beto", "antes")

        async def ana_la_ve():
            return len(await alpha.llamar.remote("linea_inicio", "ana")) == 1

        await esperar_hasta(ana_la_ve)

        await alpha.llamar.remote("dejar_de_seguir", "ana", "@beto@beta.local")

        # D11: en alpha el efecto es local e inmediato.
        assert await alpha.llamar.remote("linea_inicio", "ana") == []
        assert await alpha.llamar.remote("siguiendo", "ana") == []

        async def beta_proceso_el_undo():
            return await beta.llamar.remote("seguidores", "beto") == [DANI]

        await esperar_hasta(beta_proceso_el_undo)

        despues = await beta.llamar.remote("publicar", "beto", "despues")

        async def dani_la_ve():
            inicio = await alpha.llamar.remote("linea_inicio", "dani")
            return despues.uri in [e.publicacion.uri for e in inicio]

        await esperar_hasta(dani_la_ve)
        assert await alpha.llamar.remote("linea_inicio", "ana") == []

    asyncio.run(cuerpo())
