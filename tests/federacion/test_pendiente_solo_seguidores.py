"""Etapa E.6: solicitud de seguimiento pendiente y publicación "solo seguidores"
(docs/visibilidad.md; docs/fallos.md, 6).

Ana (alpha) pide seguir a Bea (beta, cuenta protegida). Mientras la solicitud está
pendiente, Bea publica (una pública y una "solo seguidores"): ninguna sale hacia alpha,
porque alpha no tiene seguidores aceptados de Bea. Para comprobar que "no llegó nada" sin
esperar un tiempo arbitrario se usa el orden FIFO por destino (D6) como barrera: después de
aceptar, Bea publica otra; cuando esa llega a alpha, lo anterior ya habría llegado.
"""

import asyncio

from tests.federacion.ayudas import ANA, esperar_hasta, uris


def test_pendiente_no_ve_solo_seguidores(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]
        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "bea", "Bea", protegida=True)
        await alpha.llamar.remote("seguir", "ana", "@bea@beta.local")

        async def solicitud_recibida():
            return await beta.llamar.remote("solicitudes", "bea") == [ANA]

        await esperar_hasta(solicitud_recibida)

        await beta.llamar.remote("publicar", "bea", "privada", "followers")
        await beta.llamar.remote("publicar", "bea", "pública")
        assert (await beta.transporte.remote())["pendientes"] == []

        # Lo que Ana ve desde alpha: nada de Bea, ni en el inicio ni en el perfil.
        assert await alpha.llamar.remote("linea_inicio", "ana") == []
        assert await alpha.llamar.remote("linea_perfil", "@bea@beta.local", "ana") == []

        await beta.llamar.remote("aceptar", "bea", ANA)
        barrera = await beta.llamar.remote("publicar", "bea", "ya aceptada", "followers")

        async def llego_la_barrera():
            return barrera.uri in uris(await alpha.llamar.remote("linea_inicio", "ana"))

        await esperar_hasta(llego_la_barrera)
        # Aceptar no trae el historial: solo lo publicado después.
        assert uris(await alpha.llamar.remote("linea_inicio", "ana")) == [barrera.uri]

    asyncio.run(cuerpo())
