"""Flujo 1: publicar y llegar a un seguidor remoto (docs/arquitectura.md, 4.1)."""

import asyncio

from tests.federacion.ayudas import esperar_hasta


def test_publicar_llega_a_seguidor_remoto(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def beta_acepto_el_follow():
            # El Follow tiene que llegar y procesarse en beta: es beta quien decide a
            # quién hacer fan-out al publicar, no el estado local (sincrónico) de alpha.
            seguidores = await beta.llamar.remote("seguidores", "beto")
            return len(seguidores) == 1

        await esperar_hasta(beta_acepto_el_follow)

        publicacion = await beta.llamar.remote("publicar", "beto", "Hola desde beta")

        async def ana_la_ve():
            linea = await alpha.llamar.remote("linea_inicio", "ana")
            return len(linea) == 1

        await esperar_hasta(ana_la_ve)
        linea = await alpha.llamar.remote("linea_inicio", "ana")
        assert linea[0].publicacion.uri == publicacion.uri
        assert linea[0].publicacion.contenido == "Hola desde beta"

    asyncio.run(cuerpo())
