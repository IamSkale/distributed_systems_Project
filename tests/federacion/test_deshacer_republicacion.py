"""Flujo 5: deshacer una republicación de forma remota (`Undo(Announce)`)."""

import asyncio

from tests.federacion.ayudas import armar_cadena, esperar_hasta


def test_deshacer_republicacion_remota(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local", "gamma.local")
        alpha, gamma = servidores["alpha.local"], servidores["gamma.local"]
        hola = await armar_cadena(servidores)

        await alpha.llamar.remote("deshacer_republicacion", "ana", hola.uri)

        # En alpha el efecto es local e inmediato; la publicación de Beto sigue en el
        # inicio de Ana porque ella sigue a Beto.
        assert await alpha.llamar.remote("linea_perfil", "@ana@alpha.local") == []
        inicio_ana = await alpha.llamar.remote("linea_inicio", "ana")
        assert [e.publicacion.uri for e in inicio_ana] == [hola.uri]
        assert inicio_ana[0].republicacion is None

        async def gamma_la_quito():
            inicio_caro = await gamma.llamar.remote("linea_inicio", "caro")
            perfil_ana = await gamma.llamar.remote("linea_perfil", "@ana@alpha.local")
            return inicio_caro == [] and perfil_ana == []

        await esperar_hasta(gamma_la_quito)
        assert (await gamma.estado.remote())["republicaciones"] == 0

    asyncio.run(cuerpo())
