import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from bluejay.dominio.actividades import (
    ActividadInvalida,
    crear_accept,
    crear_announce,
    crear_create,
    crear_delete,
    crear_follow,
    crear_reject,
    crear_undo,
    fecha_a_texto,
    note,
    publicacion_desde_note,
    republicacion_desde_announce,
    texto_a_fecha,
    validar,
    validar_note,
)
from bluejay.dominio.modelos import Publicacion, Republicacion

ANA = "https://alpha.local/users/ana"
BETO = "https://beta.local/users/beto"
T0 = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def publicacion(visibilidad="public"):
    return Publicacion(
        uri="https://beta.local/posts/1",
        autor=BETO,
        contenido="Hola desde beta",
        visibilidad=visibilidad,
        publicada=T0,
    )


def republicacion():
    return Republicacion(
        uri="https://alpha.local/activities/r1",
        actor=ANA,
        publicacion="https://beta.local/posts/1",
        publicada=T0,
    )


# --- Fechas ---


def test_fecha_ida_y_vuelta_en_utc():
    texto = fecha_a_texto(T0)
    assert texto == "2026-11-20T15:00:00Z"
    assert texto_a_fecha(texto) == T0


def test_fecha_en_otra_zona_se_normaliza_a_utc():
    menos_cinco = datetime(2026, 11, 20, 10, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert fecha_a_texto(menos_cinco) == "2026-11-20T15:00:00Z"


@pytest.mark.parametrize("texto", ["2026-11-20T15:00:00", "ayer", ""])
def test_fechas_invalidas(texto):
    with pytest.raises(ActividadInvalida):
        texto_a_fecha(texto)


# --- Construcción + validación (ida y vuelta) ---


def test_create_ida_y_vuelta():
    actividad = crear_create(publicacion())
    validada = validar(actividad, "beta.local")
    assert validada == actividad
    assert actividad["id"].startswith("https://beta.local/activities/")
    assert publicacion_desde_note(validada["object"]).contenido == "Hola desde beta"


def test_create_conserva_todos_los_datos_de_la_publicacion():
    original = publicacion("followers")
    copia = publicacion_desde_note(validar(crear_create(original), "beta.local")["object"])
    assert (copia.uri, copia.autor, copia.contenido, copia.visibilidad, copia.publicada) == (
        original.uri,
        original.autor,
        original.contenido,
        original.visibilidad,
        original.publicada,
    )


def test_delete_ida_y_vuelta():
    actividad = crear_delete(BETO, "https://beta.local/posts/1")
    assert validar(actividad, "beta.local") == actividad


def test_announce_ida_y_vuelta_y_su_id_es_la_uri_de_la_republicacion():
    actividad = crear_announce(republicacion())
    assert actividad["id"] == "https://alpha.local/activities/r1"
    original = republicacion()
    copia = republicacion_desde_announce(validar(actividad, "alpha.local"))
    # `recibida` es la hora de llegada a cada servidor: no viaja en la actividad.
    assert (copia.uri, copia.actor, copia.publicacion, copia.publicada) == (
        original.uri,
        original.actor,
        original.publicacion,
        original.publicada,
    )


def test_follow_accept_reject_ida_y_vuelta():
    follow = crear_follow(ANA, BETO)
    assert validar(follow, "alpha.local") == follow

    for respuesta in (crear_accept(follow), crear_reject(follow)):
        assert respuesta["actor"] == BETO
        assert respuesta["object"]["id"] == follow["id"]
        assert validar(respuesta, "beta.local") == respuesta


def test_undo_de_follow_y_de_announce():
    for original, remitente in (
        (crear_follow(ANA, BETO), "alpha.local"),
        (crear_announce(republicacion()), "alpha.local"),
    ):
        undo = crear_undo(original)
        assert undo["object"]["id"] == original["id"]
        assert validar(undo, remitente) == undo


def test_no_se_puede_deshacer_un_create():
    with pytest.raises(ValueError):
        crear_undo(crear_create(publicacion()))


def test_las_actividades_son_json():
    follow = crear_follow(ANA, BETO)
    for actividad in (
        crear_create(publicacion()),
        crear_delete(BETO, "https://beta.local/posts/1"),
        crear_announce(republicacion()),
        follow,
        crear_accept(follow),
        crear_undo(follow),
    ):
        assert json.loads(json.dumps(actividad)) == actividad


def test_cada_actividad_tiene_id_unico():
    assert crear_follow(ANA, BETO)["id"] != crear_follow(ANA, BETO)["id"]


# --- Compatibilidad hacia adelante (Conf. 4) ---


def test_los_campos_desconocidos_se_ignoran():
    actividad = crear_create(publicacion())
    actividad["campo_nuevo"] = "de una versión futura"
    actividad["object"]["otro_campo"] = 42
    validada = validar(actividad, "beta.local")
    assert "campo_nuevo" not in validada
    assert "otro_campo" not in validada["object"]


def test_delete_acepta_el_objeto_incrustado():
    actividad = crear_delete(BETO, "https://beta.local/posts/1")
    actividad["object"] = {"id": "https://beta.local/posts/1", "type": "Tombstone"}
    assert validar(actividad, "beta.local")["object"] == "https://beta.local/posts/1"


# --- Rechazos (poison pills, D6) ---


def _con(actividad, **cambios):
    return {**actividad, **cambios}


@pytest.mark.parametrize(
    "actividad",
    [
        "no soy un diccionario",
        {"type": "Like", "id": "https://beta.local/activities/1", "actor": BETO},
        _con(crear_follow(ANA, BETO), id=""),
        _con(crear_follow(ANA, BETO), actor="https://alpha.local/posts/1"),
        _con(crear_follow(ANA, BETO), object=ANA),
        _con(crear_follow(ANA, BETO), object="no es una uri"),
    ],
    ids=[
        "no-dict",
        "tipo-desconocido",
        "sin-id",
        "actor-no-es-actor",
        "seguirse-a-si-mismo",
        "objeto-invalido",
    ],
)
def test_actividades_mal_formadas(actividad):
    with pytest.raises(ActividadInvalida):
        validar(actividad, "alpha.local")


def test_el_actor_debe_ser_del_dominio_que_entrega():
    with pytest.raises(ActividadInvalida):
        validar(crear_follow(ANA, BETO), "gamma.local")


def test_el_id_debe_ser_del_dominio_que_entrega():
    follow = _con(crear_follow(ANA, BETO), id="https://gamma.local/activities/1")
    with pytest.raises(ActividadInvalida):
        validar(follow, "alpha.local")


def test_create_de_una_publicacion_de_otro_autor():
    actividad = crear_create(publicacion())
    actividad["object"]["attributedTo"] = "https://beta.local/users/otro"
    with pytest.raises(ActividadInvalida):
        validar(actividad, "beta.local")


@pytest.mark.parametrize(
    "cambio",
    [
        {"visibility": "direct"},
        {"published": "2026-11-20T15:00:00"},
        {"content": None},
        {"type": "Article"},
        {"id": "https://gamma.local/posts/1"},
    ],
)
def test_create_con_note_invalido(cambio):
    actividad = crear_create(publicacion())
    actividad["object"].update(cambio)
    with pytest.raises(ActividadInvalida):
        validar(actividad, "beta.local")


def test_solo_se_pueden_eliminar_objetos_propios():
    with pytest.raises(ActividadInvalida):
        validar(crear_delete(BETO, "https://alpha.local/posts/1"), "beta.local")


def test_solo_el_seguido_puede_aceptar():
    follow = crear_follow(ANA, BETO)
    accept = _con(crear_accept(follow), actor="https://beta.local/users/otro")
    with pytest.raises(ActividadInvalida):
        validar(accept, "beta.local")


def test_solo_quien_hizo_la_actividad_puede_deshacerla():
    undo = crear_undo(crear_follow(ANA, BETO))
    undo["actor"] = "https://alpha.local/users/otro"
    with pytest.raises(ActividadInvalida):
        validar(undo, "alpha.local")


# --- obtener_objeto (D12) ---


def test_validar_note_obtenido_del_origen():
    objeto = note(publicacion())
    assert validar_note(objeto, "beta.local") == objeto
    with pytest.raises(ActividadInvalida):
        validar_note(objeto, "gamma.local")  # gamma no puede responder por beta
