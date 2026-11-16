import pickle
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from bluejay.dominio.modelos import (
    ActorRemoto,
    Entrega,
    EstadoSeguimiento,
    Publicacion,
    Republicacion,
    Seguimiento,
    Tombstone,
    Usuario,
    Visibilidad,
    dominio_de,
    handle_desde_uri,
    parsear_handle,
    uri_actividad,
    uri_actor,
    uri_desde_handle,
    uri_publicacion,
)

ANA = "https://alpha.local/users/ana"
BETO = "https://beta.local/users/beto"
T0 = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def publicacion(uri="https://beta.local/posts/1", publicada=T0, visibilidad="public"):
    return Publicacion(
        uri=uri, autor=BETO, contenido="Hola", visibilidad=visibilidad, publicada=publicada
    )


# --- Identificadores ---


def test_uris_tienen_forma_de_url_y_su_dominio_es_el_origen():
    assert uri_actor("alpha.local", "ana") == ANA
    assert dominio_de(uri_publicacion("beta.local")) == "beta.local"
    assert uri_actividad("alpha.local").startswith("https://alpha.local/activities/")
    assert uri_publicacion("alpha.local") != uri_publicacion("alpha.local")


@pytest.mark.parametrize("handle", ["@ana@alpha.local", "ana@alpha.local", "  @ana@alpha.local "])
def test_parsear_handle(handle):
    assert parsear_handle(handle) == ("ana", "alpha.local")


@pytest.mark.parametrize("handle", ["ana", "@ana", "@Ana@alpha.local", "@ana@", "@a b@alpha.local"])
def test_parsear_handle_invalido(handle):
    with pytest.raises(ValueError):
        parsear_handle(handle)


def test_handle_y_uri_son_inversos():
    assert uri_desde_handle("@ana@alpha.local") == ANA
    assert handle_desde_uri(ANA) == "@ana@alpha.local"


def test_handle_desde_uri_rechaza_uris_que_no_son_actores():
    with pytest.raises(ValueError):
        handle_desde_uri("https://alpha.local/posts/1")


# --- Actores ---


def test_usuario_expone_uri_y_handle():
    ana = Usuario("ana", "alpha.local", "Ana")
    assert ana.uri == ANA
    assert ana.handle == "@ana@alpha.local"
    assert not ana.protegida


@pytest.mark.parametrize("username", ["", "Ana", "ana.b", "a" * 31])
def test_usuario_con_nombre_invalido(username):
    with pytest.raises(ValueError):
        Usuario(username, "alpha.local", "X")


def test_actor_remoto_deriva_dominio_y_handle_de_su_uri():
    beto = ActorRemoto(BETO, "Beto", protegida=True)
    assert beto.dominio == "beta.local"
    assert beto.handle == "@beto@beta.local"


# --- Contenido ---


def test_visibilidad_se_convierte_desde_texto():
    assert publicacion(visibilidad="followers").visibilidad is Visibilidad.SEGUIDORES


def test_visibilidad_desconocida_falla():
    with pytest.raises(ValueError):
        publicacion(visibilidad="direct")


def test_solo_las_publicas_son_republicables():
    assert publicacion(visibilidad="public").es_republicable
    assert not publicacion(visibilidad="followers").es_republicable


def test_orden_por_fecha_de_origen_y_desempate_por_uri():
    tardia = publicacion("https://beta.local/posts/b", publicada=T0)
    temprana = publicacion("https://beta.local/posts/z", publicada=T0 - timedelta(minutes=1))
    empate = publicacion("https://beta.local/posts/a", publicada=T0)
    ordenadas = sorted([tardia, temprana, empate], key=lambda p: p.clave_orden)
    assert ordenadas == [temprana, empate, tardia]


def test_fechas_sin_zona_horaria_se_rechazan():
    with pytest.raises(ValueError):
        publicacion(publicada=datetime(2026, 11, 20, 15, 0))


def test_publicacion_es_inmutable():
    with pytest.raises(FrozenInstanceError):
        publicacion().contenido = "otro"


def test_republicacion_y_tombstone():
    rep = Republicacion(
        uri="https://alpha.local/activities/1",
        actor=ANA,
        publicacion="https://beta.local/posts/1",
        publicada=T0,
    )
    assert rep.clave_orden == (T0, "https://alpha.local/activities/1")
    assert Tombstone("https://beta.local/posts/1").uri == "https://beta.local/posts/1"


# --- Relaciones ---


def test_seguimiento_empieza_pendiente_y_se_acepta():
    s = Seguimiento(seguidor=ANA, seguido=BETO)
    assert s.estado is EstadoSeguimiento.PENDIENTE and not s.aceptado
    s.aceptar()
    assert s.aceptado


def test_no_se_puede_seguir_a_si_mismo():
    with pytest.raises(ValueError):
        Seguimiento(seguidor=ANA, seguido=ANA)


# --- Comunicación ---

CREATE = {"id": "https://beta.local/activities/1", "type": "Create", "actor": BETO}


def test_entrega_expone_el_id_de_su_actividad():
    entrega = Entrega("alpha.local", CREATE)
    assert entrega.destino == "alpha.local"
    assert entrega.id_actividad == "https://beta.local/activities/1"


@pytest.mark.parametrize("campo", ["id", "type", "actor"])
def test_entrega_exige_los_campos_obligatorios(campo):
    incompleta = {k: v for k, v in CREATE.items() if k != campo}
    with pytest.raises(ValueError):
        Entrega("alpha.local", incompleta)


def test_entrega_con_destino_invalido():
    with pytest.raises(ValueError):
        Entrega("https://alpha.local", CREATE)


# --- Serialización (Ray copia los objetos entre actores con pickle) ---


@pytest.mark.parametrize(
    "objeto",
    [
        Usuario("ana", "alpha.local", "Ana"),
        ActorRemoto(BETO, "Beto"),
        publicacion(),
        Tombstone("https://beta.local/posts/1"),
        Seguimiento(seguidor=ANA, seguido=BETO),
        Entrega("alpha.local", CREATE),
    ],
)
def test_los_modelos_sobreviven_pickle(objeto):
    assert pickle.loads(pickle.dumps(objeto)) == objeto
