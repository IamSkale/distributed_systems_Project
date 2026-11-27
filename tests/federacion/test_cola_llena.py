"""Flujo 7 (parte A): la cola acotada por destino manda a dead letter con "cola llena" (D6)."""

import asyncio

from tests.federacion.ayudas import esperar_hasta


def test_cola_llena_va_a_dead_letter(crear_servidores, config):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local")
        alpha, beta = servidores["alpha.local"], servidores["beta.local"]

        await alpha.llamar.remote("registrar_usuario", "beto", "Beto")
        await beta.llamar.remote("registrar_usuario", "caro", "Caro")
        await beta.llamar.remote("seguir", "caro", "@beto@alpha.local")

        async def alpha_acepto_y_entrego_el_accept():
            # Es alpha (servidor de beto) quien decide los destinos al publicar. Además,
            # el Accept de ese Follow tiene que haber salido de la cola alpha -> beta antes
            # de pausarla: si no, ocuparía un lugar y la cuenta de abajo no cerraría.
            seguidores = await alpha.llamar.remote("seguidores", "beto")
            transporte = await alpha.transporte.remote()
            return len(seguidores) == 1 and transporte["pendientes"] == []

        await esperar_hasta(alpha_acepto_y_entrego_el_accept)

        # Alpha se desconecta: su propio entregador se pausa (D14), pero "publicar" sigue
        # funcionando porque es una operación local.
        await alpha.set_online.remote(False)

        total = config.tamano_cola + 2
        for i in range(total):
            await alpha.llamar.remote("publicar", "beto", f"mensaje {i}")

        async def cola_estabilizada():
            transporte = await alpha.transporte.remote()
            return len(transporte["pendientes"]) + len(transporte["dead_letters"]) == total

        await esperar_hasta(cola_estabilizada, timeout=5.0)

        transporte = await alpha.transporte.remote()
        assert len(transporte["pendientes"]) == config.tamano_cola
        assert len(transporte["dead_letters"]) == total - config.tamano_cola
        assert all(d["motivo"] == "cola llena" for d in transporte["dead_letters"])

    asyncio.run(cuerpo())
