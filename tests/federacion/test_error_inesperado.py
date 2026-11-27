"""Un error inesperado del receptor no traba la cola de ese destino (D6, *poison pill*).

Se registra en el namespace de la prueba un actor falso con el nombre `beta.local` cuyo
`inbox` falla con un error que no es ni `ActividadInvalida` ni de transporte.
"""

import asyncio

import ray

from tests.federacion.ayudas import esperar_hasta


@ray.remote(num_cpus=0)
class ServidorRoto:
    async def ping(self) -> bool:
        return True

    async def inbox(self, actividad, dominio_remitente) -> None:
        raise RuntimeError("fallo interno al procesar")


def test_error_inesperado_va_a_dead_letter_y_la_cola_sigue(crear_servidores, namespace):
    roto = ServidorRoto.options(name="beta.local", namespace=namespace).remote()
    ray.get(roto.ping.remote())
    try:

        async def cuerpo():
            alpha = crear_servidores("alpha.local")["alpha.local"]
            await alpha.llamar.remote("registrar_usuario", "ana", "Ana")

            # Dos actividades a la misma cola alpha -> beta: si la primera la trabara, la
            # segunda quedaría pendiente para siempre.
            await alpha.llamar.remote("seguir", "ana", "@beto@beta.local")
            await alpha.llamar.remote("seguir", "ana", "@bea@beta.local")

            async def ambas_en_dead_letter():
                return len((await alpha.transporte.remote())["dead_letters"]) == 2

            await esperar_hasta(ambas_en_dead_letter)

            transporte = await alpha.transporte.remote()
            assert transporte["pendientes"] == []
            assert all(
                d["motivo"].startswith("error inesperado") for d in transporte["dead_letters"]
            )

        asyncio.run(cuerpo())
    finally:
        ray.kill(roto)
