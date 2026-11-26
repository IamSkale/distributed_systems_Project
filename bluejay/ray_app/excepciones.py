"""Errores propios de la capa de Ray (D14, D16)."""

from __future__ import annotations

from ray.exceptions import RayActorError

from bluejay.ray_app.directorio import ServidorDesconocido


class ServidorNoDisponible(Exception):
    """El `ServidorActor` está marcado offline: la federación no se procesa (D14).

    El `EntregadorActor` la trata como error de transporte (reintentable), igual que
    `RayActorError` o un timeout: no es culpa de la actividad, es que el destino no
    está disponible ahora.
    """


# Errores de transporte: no es culpa de la actividad, se reintenta (D6, D12, D16).
# `ActividadInvalida` (del núcleo) queda fuera a propósito: esa no se reintenta.
ERRORES_TRANSPORTE = (RayActorError, ServidorNoDisponible, ServidorDesconocido, TimeoutError)
