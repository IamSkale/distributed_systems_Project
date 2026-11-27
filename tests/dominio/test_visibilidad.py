from datetime import UTC, datetime

import pytest

from bluejay.dominio.modelos import Publicacion
from bluejay.dominio.visibilidad import destinos, puede_ver, servidor_puede_ver

BETO = "https://beta.local/users/beto"
ANA = "https://alpha.local/users/ana"
CARO = "https://gamma.local/users/caro"
DANI = "https://alpha.local/users/dani"
T0 = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def publicacion(visibilidad):
    return Publicacion(
        uri="https://beta.local/posts/1",
        autor=BETO,
        contenido="hola",
        visibilidad=visibilidad,
        publicada=T0,
    )


# docs/visibilidad.md, sección 4: una fila por observador.
@pytest.mark.parametrize(
    ("observador", "ve_publica", "ve_seguidores"),
    [
        (BETO, True, True),  # el propio autor
        (ANA, True, True),  # seguidor aceptado
        (CARO, True, False),  # solicitud pendiente: no está en la lista de aceptados
        (DANI, True, False),  # no lo sigue
        (None, True, False),  # anónimo
    ],
)
def test_tabla_de_perfil(observador, ve_publica, ve_seguidores):
    aceptados = [ANA]
    assert puede_ver(publicacion("public"), observador, aceptados) is ve_publica
    assert puede_ver(publicacion("followers"), observador, aceptados) is ve_seguidores


def test_destinos_una_entrega_por_servidor_sin_el_local():
    seguidores = [ANA, DANI, CARO, "https://beta.local/users/eva"]
    assert destinos(seguidores, "beta.local") == {"alpha.local", "gamma.local"}


def test_sin_seguidores_aceptados_no_sale_nada():
    assert destinos([], "beta.local") == set()


def test_servidor_puede_obtener_publica_pero_no_solo_seguidores_sin_seguidores():
    assert servidor_puede_ver(publicacion("public"), "gamma.local", [ANA])
    assert servidor_puede_ver(publicacion("followers"), "alpha.local", [ANA])
    assert not servidor_puede_ver(publicacion("followers"), "gamma.local", [ANA])
