"""Etapa E.4: actividad duplicada (D7; docs/fallos.md, 4).

La entrega es *at-least-once*: si el `timeout` del entregador vence después de que el
receptor procesó la actividad (se pierde el "ACK", Conf. 4), el entregador la reintenta y
llega dos veces. Se simula entregando el mismo `Create` dos veces al `inbox` de alpha, y
una tercera con otro ID de actividad para la misma publicación.
"""

import asyncio

from bluejay.dominio import actividades as act
from bluejay.dominio.modelos import Publicacion, ahora, uri_publicacion
from tests.federacion.ayudas import BETO, esperar_hasta, uris


def test_create_duplicado_aparece_una_vez(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]
        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def ana_sigue_a_beto():
            return await alpha.llamar.remote("siguiendo", "ana") == [BETO]

        await esperar_hasta(ana_sigue_a_beto)

        hola = Publicacion(
            uri=uri_publicacion("beta.local"),
            autor=BETO,
            contenido="hola",
            visibilidad="public",
            publicada=ahora(),
        )
        create = act.crear_create(hola)

        await alpha.inbox.remote(create, "beta.local")
        procesadas = (await alpha.estado.remote())["actividades_procesadas"]

        # Mismo ID: lo descarta la deduplicación sin volver a procesarlo.
        await alpha.inbox.remote(create, "beta.local")
        assert (await alpha.estado.remote())["actividades_procesadas"] == procesadas

        # Otro ID, misma publicación: lo frena el handler, que es idempotente por sí mismo.
        await alpha.inbox.remote(act.crear_create(hola), "beta.local")

        assert uris(await alpha.llamar.remote("linea_inicio", "ana")) == [hola.uri]
        assert (await alpha.estado.remote())["publicaciones"] == 1

    asyncio.run(cuerpo())
