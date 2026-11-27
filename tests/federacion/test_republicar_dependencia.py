"""Flujo 3: republicar contenido de un tercer servidor (docs/arquitectura.md, 4.3, D12).

Caro (gamma) sigue a Ana (alpha) pero no a Beto (beta): cuando Ana republica una
publicación de Beto, gamma no tiene el original y lo pide a beta con `obtener_objeto`.
"""

import asyncio

from tests.federacion.ayudas import armar_cadena


def test_republicar_resuelve_dependencia(crear_servidores):
    async def cuerpo():
        servidores = crear_servidores("alpha.local", "beta.local", "gamma.local")
        hola = await armar_cadena(servidores)

        linea = await servidores["gamma.local"].llamar.remote("linea_inicio", "caro")
        assert linea[0].publicacion.uri == hola.uri
        assert linea[0].republicacion is not None
        assert linea[0].republicacion.actor == "https://alpha.local/users/ana"

        # Resuelto el original, gamma ya no espera nada.
        estado_gamma = await servidores["gamma.local"].estado.remote()
        assert estado_gamma["dependencias_pendientes"] == 0

    asyncio.run(cuerpo())
