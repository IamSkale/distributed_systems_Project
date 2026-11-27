import pickle
from datetime import UTC, datetime, timedelta

from bluejay.dominio.lineas import ElementoLinea, LineaInicio, ordenar
from bluejay.dominio.modelos import Publicacion, Republicacion

BETO = "https://beta.local/users/beto"
ANA = "https://alpha.local/users/ana"
DANI = "https://alpha.local/users/dani"
T0 = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


def pub(n, minutos=0, autor=BETO):
    return Publicacion(
        uri=f"https://beta.local/posts/{n}",
        autor=autor,
        contenido=f"post {n}",
        visibilidad="public",
        publicada=T0 + timedelta(minutes=minutos),
    )


def rep(n, original, actor, minutos=0):
    return Republicacion(
        uri=f"https://alpha.local/activities/{n}",
        actor=actor,
        publicacion=original.uri,
        publicada=T0 + timedelta(minutes=minutos),
    )


def almacen(*publicaciones):
    return {p.uri: p for p in publicaciones}


def test_orden_de_mas_reciente_a_mas_antigua():
    p1, p2, p3 = pub(1, 0), pub(2, 10), pub(3, 5)
    linea = LineaInicio()
    for p in (p1, p2, p3):
        linea.agregar_publicacion(p)
    uris = [e.publicacion.uri for e in linea.elementos(almacen(p1, p2, p3))]
    assert uris == [p2.uri, p3.uri, p1.uri]


def test_empate_de_hora_se_desempata_por_uri():
    a, b = pub("a", 0), pub("b", 0)
    assert [e.publicacion.uri for e in ordenar([ElementoLinea(a), ElementoLinea(b)])] == [
        b.uri,
        a.uri,
    ]


def test_republicacion_se_ordena_por_hora_de_republicacion():
    vieja, nueva = pub(1, 0), pub(2, 10)
    linea = LineaInicio()
    linea.agregar_publicacion(nueva)
    linea.agregar_republicacion(rep("r", vieja, ANA, minutos=20))
    primero = linea.elementos(almacen(vieja, nueva))[0]
    assert primero.publicacion == vieja
    assert primero.mostrada_por == ANA


def test_limite():
    publicaciones = [pub(n, n) for n in range(5)]
    linea = LineaInicio()
    for p in publicaciones:
        linea.agregar_publicacion(p)
    assert len(linea.elementos(almacen(*publicaciones), limite=2)) == 2


def test_misma_publicacion_por_dos_caminos_aparece_una_vez_con_el_primero():
    """D10."""
    original = pub(1)
    linea = LineaInicio()
    linea.agregar_republicacion(rep("r1", original, ANA, 1))
    linea.agregar_republicacion(rep("r2", original, DANI, 2))
    elementos = linea.elementos(almacen(original))
    assert len(elementos) == 1
    assert elementos[0].mostrada_por == ANA


def test_agregar_dos_veces_es_idempotente():
    original = pub(1)
    linea = LineaInicio()
    linea.agregar_publicacion(original)
    linea.agregar_publicacion(original)
    assert len(linea) == 1


def test_quitar_republicacion_deja_ver_el_siguiente_motivo():
    original = pub(1)
    r1, r2 = rep("r1", original, ANA, 1), rep("r2", original, DANI, 2)
    linea = LineaInicio()
    linea.agregar_republicacion(r1)
    linea.agregar_republicacion(r2)
    linea.quitar_republicacion(original.uri, r1.uri)
    assert linea.elementos(almacen(original))[0].mostrada_por == DANI
    linea.quitar_republicacion(original.uri, r2.uri)
    assert original.uri not in linea


def test_quitar_actor_conserva_lo_que_llego_por_otro_camino():
    """D11: dejo de seguir a Beto, pero Ana (a quien sigo) había republicado algo suyo."""
    p1, p2 = pub(1), pub(2)
    linea = LineaInicio()
    linea.agregar_publicacion(p1)
    linea.agregar_publicacion(p2)
    linea.agregar_republicacion(rep("r", p2, ANA))
    linea.quitar_actor(BETO)
    elementos = linea.elementos(almacen(p1, p2))
    assert [(e.publicacion.uri, e.mostrada_por) for e in elementos] == [(p2.uri, ANA)]


def test_quitar_publicacion_quita_sus_republicaciones():
    original = pub(1)
    linea = LineaInicio()
    linea.agregar_publicacion(original)
    linea.agregar_republicacion(rep("r", original, ANA))
    linea.quitar_publicacion(original.uri)
    assert len(linea) == 0


def test_publicacion_ausente_del_almacen_no_se_muestra():
    original = pub(1)
    linea = LineaInicio()
    linea.agregar_publicacion(original)
    assert linea.elementos({}) == []


def test_elemento_sobrevive_a_pickle():
    """Ray copia los valores de retorno serializándolos."""
    original = pub(1)
    elemento = ElementoLinea(original, rep("r", original, ANA))
    assert pickle.loads(pickle.dumps(elemento)) == elemento
