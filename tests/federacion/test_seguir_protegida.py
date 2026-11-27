"""Flujo 2: seguir una cuenta protegida remota, aceptada o rechazada (docs/arquitectura.md, 4.2)."""

import asyncio

from tests.federacion.ayudas import esperar_hasta


def test_seguir_protegida_remota(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto", protegida=True)

        seguimiento = await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")
        assert str(seguimiento.estado) == "pending"

        async def beta_tiene_solicitud():
            solicitudes = await beta.llamar.remote("solicitudes", "beto")
            return len(solicitudes) == 1

        await esperar_hasta(beta_tiene_solicitud)

        await beta.llamar.remote("aceptar", "beto", "https://alpha.local/users/ana")

        async def ana_quedo_aceptada():
            siguiendo = await alpha.llamar.remote("siguiendo", "ana")
            return len(siguiendo) == 1

        await esperar_hasta(ana_quedo_aceptada)

        publicacion = await beta.llamar.remote("publicar", "beto", "Solo para aceptados")

        async def ana_la_ve():
            linea = await alpha.llamar.remote("linea_inicio", "ana")
            return len(linea) == 1

        await esperar_hasta(ana_la_ve)
        linea = await alpha.llamar.remote("linea_inicio", "ana")
        assert linea[0].publicacion.uri == publicacion.uri

    asyncio.run(cuerpo())


def test_rechazar_protegida_remota(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto", protegida=True)

        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def beta_tiene_solicitud():
            return len(await beta.llamar.remote("solicitudes", "beto")) == 1

        await esperar_hasta(beta_tiene_solicitud)

        await beta.llamar.remote("rechazar", "beto", "https://alpha.local/users/ana")
        assert await beta.llamar.remote("solicitudes", "beto") == []
        assert await beta.llamar.remote("seguidores", "beto") == []

        async def alpha_recibio_el_reject():
            perfil = await alpha.llamar.remote("perfil", "@beto@beta.local", visto_por="ana")
            return perfil["relacion"] is None

        await esperar_hasta(alpha_recibio_el_reject)
        assert await alpha.llamar.remote("siguiendo", "ana") == []

    asyncio.run(cuerpo())
