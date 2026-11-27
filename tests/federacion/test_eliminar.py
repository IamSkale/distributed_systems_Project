"""Flujo 4: eliminar una publicación propia (docs/arquitectura.md, 4.4, D13).

El `Delete` tiene que llegar a quien recibió la publicación (alpha, por el `Create`) y a
quien la pidió con `obtener_objeto` (gamma, por la republicación de Ana).
"""

import asyncio

from tests.federacion.ayudas import armar_cadena, esperar_hasta


def test_eliminar_desaparece_en_alpha_y_en_gamma(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local", "gamma.local")
        alpha, beta, gamma = (
            servidores["alpha.local"],
            servidores["beta.local"],
            servidores["gamma.local"],
        )
        hola = await armar_cadena(servidores)

        await beta.llamar.remote("eliminar", "beto", hola.uri)

        async def desaparecio_en_ambos():
            inicio_ana = await alpha.llamar.remote("linea_inicio", "ana")
            inicio_caro = await gamma.llamar.remote("linea_inicio", "caro")
            return inicio_ana == [] and inicio_caro == []

        await esperar_hasta(desaparecio_en_ambos)

        # La republicación de Ana también se fue, en su perfil y en el estado de ambos.
        assert await alpha.llamar.remote("linea_perfil", "@ana@alpha.local") == []
        assert (await alpha.estado.remote())["republicaciones"] == 0
        assert (await gamma.estado.remote())["republicaciones"] == 0

        for servidor in (alpha, beta):
            assert (await servidor.transporte.remote())["dead_letters"] == []

    asyncio.run(cuerpo())
