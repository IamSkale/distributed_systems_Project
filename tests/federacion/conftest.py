"""Fixtures para probar la Etapa D con actores de Ray reales (sin mocks)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import pytest
import ray
from ray.actor import ActorHandle

from bluejay.ray_app.config import ConfigRay, config_pruebas
from bluejay.ray_app.servidor_actor import levantar_servidores


@pytest.fixture(scope="session", autouse=True)
def _cluster_ray() -> Iterable[None]:
    ray.init(num_cpus=4, log_to_driver=False, ignore_reinit_error=True)
    yield
    ray.shutdown()


@pytest.fixture
def namespace() -> str:
    """Un namespace distinto por prueba: los mismos dominios no chocan entre pruebas."""
    return f"prueba-{uuid.uuid4()}"


@pytest.fixture
def config() -> ConfigRay:
    return config_pruebas()


@pytest.fixture
def crear_servidores(namespace: str, config: ConfigRay) -> Iterable:
    creados: list[dict[str, ActorHandle]] = []

    def _crear(*dominios: str) -> dict[str, ActorHandle]:
        servidores = levantar_servidores(dominios, config, namespace)
        creados.append(servidores)
        return servidores

    yield _crear

    # Libera los actores entre pruebas: el EntregadorActor de cada servidor no queda
    # referenciado por nombre, así que hay que pedirle al ServidorActor que lo mate.
    for servidores in creados:
        for actor in servidores.values():
            try:
                ray.get(actor.destruir.remote())
            except Exception:  # noqa: BLE001 - mejor esfuerzo al limpiar
                pass
            ray.kill(actor)
