"""Flujo 7 (parte B): offline, lo local sigue vivo y lo federado rechaza (D14)."""

import asyncio

import pytest

from bluejay.ray_app.excepciones import ServidorNoDisponible


def test_offline_bloquea_federacion_pero_no_lo_local(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local")
        alpha = servidores["alpha.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await alpha.set_online.remote(False)

        # Lo local sigue funcionando sin restricciones.
        publicacion = await alpha.llamar.remote("publicar", "ana", "Sigo publicando offline")
        linea = await alpha.llamar.remote("linea_inicio", "ana")
        assert linea[0].publicacion.uri == publicacion.uri

        # Lo federado rechaza mientras está offline.
        actividad_follow = {
            "id": "https://beta.local/activities/x",
            "type": "Follow",
            "actor": "https://beta.local/users/beto",
            "object": "https://alpha.local/users/ana",
        }
        with pytest.raises(ServidorNoDisponible):
            await alpha.inbox.remote(actividad_follow, "beta.local")
        with pytest.raises(ServidorNoDisponible):
            await alpha.obtener_objeto.remote(publicacion.uri, "beta.local")
        with pytest.raises(ServidorNoDisponible):
            await alpha.obtener_actor.remote("https://alpha.local/users/ana")

        await alpha.set_online.remote(True)
        # Al reconectar, vuelve a aceptar federación.
        await alpha.inbox.remote(actividad_follow, "beta.local")

    asyncio.run(cuerpo())
