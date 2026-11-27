"""La API web sobre `BackendRay` (`BLUEJAY_BACKEND=ray`): la misma semilla que con
`BackendLocal`, pero propagada por los `EntregadorActor` (D4)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from bluejay.web.app import crear_app
from bluejay.web.backend import BackendRay


@pytest.fixture
def api(namespace, config):
    backend = BackendRay(namespace=namespace, config=config)
    try:
        with TestClient(crear_app(backend)) as cliente:  # `with` ejecuta la semilla
            yield cliente
    finally:
        asyncio.run(backend.cerrar())


def esperar_contenidos(api, ruta, esperados, timeout=5.0):
    inicio = time.monotonic()
    while True:
        respuesta = api.get(ruta)
        assert respuesta.status_code == 200, respuesta.text
        contenidos = sorted(e["contenido"] for e in respuesta.json())
        if contenidos == sorted(esperados):
            return respuesta.json()
        if time.monotonic() - inicio >= timeout:
            raise AssertionError(f"{ruta}: {contenidos} != {sorted(esperados)}")
        time.sleep(0.05)


def test_semilla_sobre_ray(api):
    servidores = api.get("/api/servidores").json()
    assert [s["dominio"] for s in servidores] == ["alpha.local", "beta.local", "gamma.local"]

    esperar_contenidos(
        api,
        "/api/alpha.local/usuarios/ana/inicio",
        ["Probando Blue Jay desde alpha", "Esto solo lo ven mis seguidores", "Hola desde beta 👋"],
    )
    # Caro sigue a Ana, no a Beto: ve la republicación (gamma pidió el original, D12) y
    # la publicación de Ana, pero no la de "solo seguidores" de Beto.
    inicio_caro = esperar_contenidos(
        api,
        "/api/gamma.local/usuarios/caro/inicio",
        ["Probando Blue Jay desde alpha", "Hola desde beta 👋"],
    )
    hola = next(e for e in inicio_caro if e["contenido"] == "Hola desde beta 👋")
    assert hola["republicacion"]["actor"]["handle"] == "@ana@alpha.local"
