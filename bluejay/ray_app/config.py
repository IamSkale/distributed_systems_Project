"""Parámetros de la capa de Ray: lo que no está en el núcleo porque es del transporte.

Se inyecta explícitamente en cada actor (sin estado global) para que las pruebas puedan
usar una configuración con tiempos cortos sin afectar al resto del proceso.
"""

from __future__ import annotations

from dataclasses import dataclass

from bluejay.dominio.servidor import LIMITE_CARACTERES


@dataclass(frozen=True, slots=True)
class ConfigRay:
    """Límites y tiempos del `EntregadorActor` y del `ServidorActor` (D6, D12)."""

    limite_caracteres: int = LIMITE_CARACTERES
    intervalo_base: float = 1.0  # segundos antes del primer reintento
    factor_backoff: float = 2.0
    maximo_intentos: int = 6  # D6: 6 intentos, con esperas de 1, 2, 4, 8 y 16 s entre ellos
    tamano_cola: int = 1000
    timeout: float = 2.0  # toda espera remota usa este timeout (asyncio.wait_for, D17)

    def backoff(self, intentos: int) -> float:
        """Segundos de espera antes del intento número `intentos` (1-based)."""
        return self.intervalo_base * (self.factor_backoff ** (intentos - 1))


def config_pruebas() -> ConfigRay:
    """Configuración para pruebas: reintentos y timeouts cortos para no esperar de verdad."""
    return ConfigRay(
        intervalo_base=0.02,
        factor_backoff=2.0,
        maximo_intentos=3,
        tamano_cola=5,
        timeout=0.5,
    )
