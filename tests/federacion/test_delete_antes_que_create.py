"""Etapa E.3: `Delete` antes que `Create` (D13; docs/fallos.md, 3).

La cola FIFO de beta hacia alpha (D6) nunca invierte el orden de dos actividades suyas,
así que el desorden se provoca entregando a mano, directo al `inbox` de alpha, como lo
haría un transporte sin orden (p. ej., dos peticiones HTTP concurrentes en la entrega
final). El *tombstone* que deja el `Delete` hace que el `Create` atrasado se ignore.
"""

import asyncio

from bluejay.dominio import actividades as act
from bluejay.dominio.modelos import Publicacion, ahora, uri_publicacion
from tests.federacion.ayudas import BETO, esperar_hasta


def test_delete_antes_que_create(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]
        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")
        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def ana_sigue_a_beto():
            return await alpha.llamar.remote("siguiendo", "ana") == [BETO]

        await esperar_hasta(ana_sigue_a_beto)

        efimera = Publicacion(
            uri=uri_publicacion("beta.local"),
            autor=BETO,
            contenido="efímera",
            visibilidad="public",
            publicada=ahora(),
        )
        create = act.crear_create(efimera)
        delete = act.crear_delete(BETO, efimera.uri)

        await alpha.inbox.remote(delete, "beta.local")
        await alpha.inbox.remote(create, "beta.local")

        assert await alpha.llamar.remote("linea_inicio", "ana") == []
        estado = await alpha.estado.remote()
        assert estado["publicaciones"] == 0
        assert estado["tombstones"] == 1

        # Un reintento del mismo Create tampoco la resucita.
        await alpha.inbox.remote(create, "beta.local")
        assert await alpha.llamar.remote("linea_inicio", "ana") == []

    asyncio.run(cuerpo())
