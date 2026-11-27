"""Etapa E.2: reintentos agotados (D6; docs/fallos.md, 2).

Con `config_pruebas` el entregador se rinde tras 3 intentos (~60 ms). Gamma sigue offline
más que eso: la entrega pasa a *dead letter* y la publicación no llega nunca a gamma, ni
siquiera al reconectarse (no hay *pull* de lo perdido en esta entrega). La cola de beta
hacia gamma no queda trabada: lo que Beto publica después sí llega.
"""

import asyncio

from tests.federacion.ayudas import BETO, esperar_hasta, uris


def test_reintentos_agotados_van_a_dead_letter(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("beta.local", "gamma.local")
        beta, gamma = servidores["beta.local"], servidores["gamma.local"]
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await gamma.llamar.remote("registrar_usuario", "caro", "Caro")
        await gamma.llamar.remote("seguir", "caro", "@beto@beta.local")

        async def caro_sigue_a_beto():
            transporte = await beta.transporte.remote()
            siguiendo = await gamma.llamar.remote("siguiendo", "caro")
            return siguiendo == [BETO] and transporte["pendientes"] == []

        await esperar_hasta(caro_sigue_a_beto)

        await gamma.set_online.remote(False)
        perdida = await beta.llamar.remote("publicar", "beto", "Esta no llega")

        async def fue_a_dead_letter():
            return len((await beta.transporte.remote())["dead_letters"]) == 1

        await esperar_hasta(fue_a_dead_letter)
        transporte = await beta.transporte.remote()
        assert transporte["pendientes"] == []
        dead_letter = transporte["dead_letters"][0]
        assert dead_letter["destino"] == "gamma.local"
        assert dead_letter["tipo"] == "Create"
        assert dead_letter["motivo"].startswith("máximo de intentos agotado")

        # La publicación sigue existiendo en su origen: solo se perdió la copia de gamma.
        assert perdida.uri in uris(await beta.llamar.remote("linea_perfil", "@beto@beta.local"))

        await gamma.set_online.remote(True)
        nueva = await beta.llamar.remote("publicar", "beto", "Esta sí llega")

        async def llega_la_nueva():
            return nueva.uri in uris(await gamma.llamar.remote("linea_inicio", "caro"))

        await esperar_hasta(llega_la_nueva)
        assert uris(await gamma.llamar.remote("linea_inicio", "caro")) == [nueva.uri]

    asyncio.run(cuerpo())
