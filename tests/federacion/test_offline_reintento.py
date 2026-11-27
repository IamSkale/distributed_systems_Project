"""Flujo 5: destino desconectado, reintentos con backoff y entrega al reconectar (D6, D14)."""

import asyncio

import pytest

from tests.federacion.ayudas import config_paciente, esperar_hasta


@pytest.fixture
def config():
    # Con `config_pruebas` los reintentos se agotan en ~60 ms: la prueba reconectaba a beta
    # "a tiempo" solo si la máquina era rápida.
    return config_paciente()


def test_reintenta_con_backoff_y_entrega_al_reconectar(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "ana", "Ana")
        await beta.llamar.remote("registrar_usuario", "beto", "Beto")

        await beta.set_online.remote(False)

        await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")

        async def hubo_al_menos_un_reintento():
            transporte = await alpha.llamar.remote("estado")  # solo para turnar el loop
            pendientes = (await alpha.transporte.remote())["pendientes"]
            return any(p["intentos"] >= 1 for p in pendientes) and transporte is not None

        await esperar_hasta(hubo_al_menos_un_reintento, timeout=3.0)

        pendientes = (await alpha.transporte.remote())["pendientes"]
        assert len(pendientes) == 1
        assert pendientes[0]["destino"] == "beta.local"

        await beta.set_online.remote(True)

        async def se_entrego():
            pendientes = (await alpha.transporte.remote())["pendientes"]
            return len(pendientes) == 0

        await esperar_hasta(se_entrego, timeout=3.0)

        dead_letters = (await alpha.transporte.remote())["dead_letters"]
        assert dead_letters == []

    asyncio.run(cuerpo())
