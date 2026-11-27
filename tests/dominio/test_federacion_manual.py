"""Federación entre núcleos conectados a mano, sin Ray (Etapa C, criterio de terminado).

Recorre los flujos de la Etapa D (plan_entrega_1.md) y los casos límite que dependen del
núcleo (Etapa E). La `Red` de `conftest.py` hace el papel del transporte.
"""

import pickle

import pytest

from bluejay.dominio import actividades as act
from bluejay.dominio.actividades import ActividadInvalida
from bluejay.dominio.modelos import EstadoSeguimiento

ANA = "https://alpha.local/users/ana"
BETO = "https://beta.local/users/beto"
CARO = "https://gamma.local/users/caro"
A, B, G = "alpha.local", "beta.local", "gamma.local"


def uris(elementos):
    return [e.publicacion.uri for e in elementos]


def seguir(red, dominio, username, handle):
    return red.hacer(dominio, red[dominio].seguir(username, handle))


@pytest.fixture
def ana_sigue_a_beto(red):
    seguir(red, A, "ana", "@beto@beta.local")
    return red


@pytest.fixture
def cadena(ana_sigue_a_beto):
    """Ana sigue a Beto, Caro sigue a Ana; Beto publicó y Ana lo republicó."""
    red = ana_sigue_a_beto
    seguir(red, G, "caro", "@ana@alpha.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "Hola desde beta"))
    republicacion = red.hacer(A, red[A].republicar("ana", publicacion.uri))
    return red, publicacion, republicacion


# --- Seguimiento ---


def test_seguir_remoto_follow_y_accept(red):
    resultado = red[A].seguir("ana", "@beto@beta.local")
    assert resultado.valor.estado is EstadoSeguimiento.PENDIENTE  # hasta que llegue el Accept
    red.hacer(A, resultado)
    assert red.tipos_entregados(B) == ["Follow"]
    assert red.tipos_entregados(A) == ["Accept"]
    assert red[A].siguiendo("ana") == [BETO]
    assert red[B].seguidores("beto") == [ANA]


def test_seguir_cuenta_protegida_remota_aceptar(red):
    red[B].registrar_usuario("bea", "Bea", protegida=True)
    seguir(red, A, "ana", "@bea@beta.local")
    assert red[B].solicitudes("bea") == [ANA]
    assert red[A].perfil("@bea@beta.local", visto_por="ana")["relacion"] == "pending"
    red.hacer(B, red[B].aceptar("bea", ANA))
    assert red[A].perfil("@bea@beta.local", visto_por="ana")["relacion"] == "accepted"


def test_seguir_cuenta_protegida_remota_rechazar(red):
    red[B].registrar_usuario("bea", "Bea", protegida=True)
    seguir(red, A, "ana", "@bea@beta.local")
    red.hacer(B, red[B].rechazar("bea", ANA))
    assert red.tipos_entregados(A) == ["Reject"]
    assert red[A].perfil("@bea@beta.local", visto_por="ana")["relacion"] is None
    assert red[B].solicitudes("bea") == []


def test_dejar_de_seguir_remoto(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    red.hacer(B, red[B].publicar("beto", "antes"))
    red.hacer(A, red[A].dejar_de_seguir("ana", "@beto@beta.local"))
    assert red[B].seguidores("beto") == []
    assert red[A].linea_inicio("ana") == []  # D11
    assert red[B].publicar("beto", "despues").entregas == []  # alpha ya no es destino


def test_accept_de_un_follow_viejo_se_ignora(red):
    """Un Accept que responde a un Follow ya deshecho no acepta la solicitud nueva."""
    red[B].registrar_usuario("bea", "Bea", protegida=True)
    primero = red[A].seguir("ana", "@bea@beta.local").entregas[0].actividad
    red[A].dejar_de_seguir("ana", "@bea@beta.local")
    red[A].seguir("ana", "@bea@beta.local")
    red[A].procesar(act.crear_accept(primero), B)
    assert red[A].perfil("@bea@beta.local", visto_por="ana")["relacion"] == "pending"


def test_follow_a_usuario_inexistente_es_invalido(red):
    follow = red[A].seguir("ana", "@nadie@beta.local").entregas[0].actividad
    with pytest.raises(ActividadInvalida):
        red[B].procesar(follow, A)


# --- Publicar (criterio de terminado de la Etapa C) ---


def test_beto_publica_y_aparece_en_el_inicio_de_ana(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    publicacion = red.hacer(B, red[B].publicar("beto", "Hola desde beta"))
    assert uris(red[A].linea_inicio("ana")) == [publicacion.uri]
    assert uris(red[A].linea_perfil("@beto@beta.local", visto_por="ana")) == [publicacion.uri]


def test_una_entrega_por_servidor_destino(ana_sigue_a_beto):
    """Shared inbox (D5): dos seguidores en alpha, una sola entrega."""
    red = ana_sigue_a_beto
    red[A].registrar_usuario("dani", "Dani")
    seguir(red, A, "dani", "@beto@beta.local")
    resultado = red[B].publicar("beto", "hola")
    assert [e.destino for e in resultado.entregas] == [A]
    publicacion = red.hacer(B, resultado)
    assert (
        uris(red[A].linea_inicio("ana")) == uris(red[A].linea_inicio("dani")) == [publicacion.uri]
    )


def test_solo_seguidores_no_sale_hacia_servidores_sin_seguidores(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    red[G].registrar_usuario("gus", "Gus")
    resultado = red[B].publicar("beto", "privada", "followers")
    assert [e.destino for e in resultado.entregas] == [A]
    publicacion = red.hacer(B, resultado)
    assert uris(red[A].linea_inicio("ana")) == [publicacion.uri]
    assert red[G].estado()["publicaciones"] == 0


def test_solo_seguidores_en_el_receptor_solo_para_seguidores(ana_sigue_a_beto):
    """En alpha solo la ve Ana, no los demás usuarios de alpha (docs/visibilidad.md, 2)."""
    red = ana_sigue_a_beto
    red[A].registrar_usuario("dani", "Dani")
    publicacion = red.hacer(B, red[B].publicar("beto", "privada", "followers"))
    assert uris(red[A].linea_perfil("@beto@beta.local", visto_por="ana")) == [publicacion.uri]
    assert red[A].linea_perfil("@beto@beta.local", visto_por="dani") == []
    assert red[A].linea_perfil("@beto@beta.local") == []


def test_publicacion_atrasada_aparece_en_su_lugar_cronologico(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    vieja = red[B].publicar("beto", "vieja")  # se queda sin entregar
    nueva = red.hacer(B, red[B].publicar("beto", "nueva"))
    red.hacer(B, vieja)
    assert uris(red[A].linea_inicio("ana")) == [nueva.uri, vieja.valor.uri]


# --- Republicar ---


def test_republicacion_llega_a_un_tercer_servidor_que_pide_el_original(cadena):
    """D12: gamma no tenía el original; lo pide a beta y luego muestra la republicación."""
    red, publicacion, republicacion = cadena
    inicio_caro = red[G].linea_inicio("caro")
    assert [(e.publicacion.uri, e.mostrada_por) for e in inicio_caro] == [(publicacion.uri, ANA)]
    assert inicio_caro[0].republicacion.uri == republicacion.uri
    assert red.tipos_entregados(G) == ["Accept", "Announce"]  # nunca recibió el Create


def test_deshacer_republicacion_remota(cadena):
    red, publicacion, _ = cadena
    red.hacer(A, red[A].deshacer_republicacion("ana", publicacion.uri))
    assert red[G].linea_inicio("caro") == []
    assert red[G].linea_perfil("@ana@alpha.local") == []
    assert red[A].linea_perfil("@ana@alpha.local") == []


def test_announce_reintentado_despues_del_undo_no_resucita(cadena):
    """Un reintento del Announce que llega tras su Undo se descarta por su ID (D7)."""
    red, publicacion, republicacion = cadena
    red.hacer(A, red[A].deshacer_republicacion("ana", publicacion.uri))
    red[G].procesar(act.crear_announce(republicacion), A)
    assert red[G].linea_inicio("caro") == []


def test_undo_que_adelanta_a_su_announce(ana_sigue_a_beto):
    """Si el Undo llega primero, el Announce atrasado ya no tiene efecto."""
    red = ana_sigue_a_beto
    seguir(red, G, "caro", "@ana@alpha.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    announce = red[A].republicar("ana", publicacion.uri).entregas[0].actividad
    undo = red[A].deshacer_republicacion("ana", publicacion.uri).entregas[0].actividad
    red[G].procesar(undo, A)
    red[G].procesar(announce, A)
    assert red[G].dependencias_pendientes() == []
    assert red[G].linea_inicio("caro") == []


def test_announce_duplicado_se_aplica_una_vez(cadena):
    red, publicacion, republicacion = cadena
    red[G].procesar(act.crear_announce(republicacion), A)
    assert len(red[G].linea_inicio("caro")) == 1


# --- Eliminar ---


def test_eliminar_remoto_desaparece_en_alpha_y_en_gamma(cadena):
    """D13: el Delete llega a quien la recibió (alpha) y a quien la pidió (gamma)."""
    red, publicacion, _ = cadena
    resultado = red[B].eliminar("beto", publicacion.uri)
    assert sorted(e.destino for e in resultado.entregas) == [A, G]
    red.hacer(B, resultado)
    assert red[A].linea_inicio("ana") == []
    assert red[G].linea_inicio("caro") == []
    assert red[A].linea_perfil("@ana@alpha.local") == []
    assert red[A].estado()["republicaciones"] == red[G].estado()["republicaciones"] == 0


def test_delete_antes_que_create(ana_sigue_a_beto):
    """El tombstone hace que el Create atrasado se ignore (D13)."""
    red = ana_sigue_a_beto
    creacion = red[B].publicar("beto", "efimera")
    borrado = red[B].eliminar("beto", creacion.valor.uri)
    red.hacer(B, borrado)
    red.hacer(B, creacion)
    assert red[A].linea_inicio("ana") == []
    assert red[A].estado()["publicaciones"] == 0


def test_pedir_un_original_eliminado_devuelve_tombstone(cadena):
    red, publicacion, _ = cadena
    red[B].eliminar("beto", publicacion.uri)  # el Delete no se entrega a nadie
    objeto = red[B].servir_objeto(publicacion.uri, G)
    assert objeto == {"id": publicacion.uri, "type": "Tombstone"}


# --- Duplicados ---


def test_create_duplicado_aparece_una_vez(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    resultado = red[B].publicar("beto", "hola")
    red.encolar(B, resultado.entregas * 2)
    red.propagar()
    assert len(red[A].linea_inicio("ana")) == 1


def test_create_con_otro_id_para_la_misma_publicacion_tambien_es_idempotente(ana_sigue_a_beto):
    """El handler es idempotente por sí mismo, no solo por el ID de actividad (D7)."""
    red = ana_sigue_a_beto
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    red[A].procesar(act.crear_create(publicacion), B)
    assert len(red[A].linea_inicio("ana")) == 1


# --- Announce de una publicación desconocida (D12) ---


def test_announce_espera_al_original_si_el_origen_esta_caido(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    seguir(red, G, "caro", "@ana@alpha.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    red.desconectados.add(B)
    red.hacer(A, red[A].republicar("ana", publicacion.uri))
    assert red[G].linea_inicio("caro") == []  # aceptado, pero esperando el original
    assert red[G].dependencias_pendientes() == [publicacion.uri]
    red.desconectados.discard(B)
    red.propagar()
    assert uris(red[G].linea_inicio("caro")) == [publicacion.uri]
    assert red[G].dependencias_pendientes() == []


def test_undo_mientras_se_espera_el_original(ana_sigue_a_beto):
    """Al volver el original, nadie lo espera: se descarta (verificar de nuevo, D17)."""
    red = ana_sigue_a_beto
    seguir(red, G, "caro", "@ana@alpha.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    red.desconectados.add(B)
    red.hacer(A, red[A].republicar("ana", publicacion.uri))
    red.hacer(A, red[A].deshacer_republicacion("ana", publicacion.uri))
    assert red[G].dependencias_pendientes() == []
    objeto = red[B].servir_objeto(publicacion.uri, G)
    red[G].recibir_objeto(objeto, B)
    assert red[G].linea_inicio("caro") == []
    assert red[G].estado()["publicaciones"] == 0


def test_original_eliminado_mientras_se_espera(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    seguir(red, G, "caro", "@ana@alpha.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    red.desconectados.add(B)
    red.hacer(A, red[A].republicar("ana", publicacion.uri))
    red[B].eliminar("beto", publicacion.uri)
    red.desconectados.discard(B)
    red.propagar()  # gamma pide el original y recibe un Tombstone
    assert red[G].dependencias_pendientes() == []
    assert red[G].linea_inicio("caro") == []


def test_obtener_objeto_respeta_la_visibilidad(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    privada = red.hacer(B, red[B].publicar("beto", "privada", "followers"))
    assert red[B].servir_objeto(privada.uri, G) is None
    assert red[B].servir_objeto(privada.uri, A)["id"] == privada.uri
    assert red[A].servir_objeto(privada.uri, G) is None  # solo el origen sirve sus objetos


def test_objeto_de_otro_dominio_es_invalido(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    objeto = red[B].servir_objeto(publicacion.uri, G)
    with pytest.raises(ActividadInvalida):
        red[G].recibir_objeto(objeto, A)


# --- Entregas en vuelo y actividades inválidas ---


def test_publicacion_que_llega_despues_del_undo_follow_no_entra(ana_sigue_a_beto):
    """D11: entregas en vuelo."""
    red = ana_sigue_a_beto
    en_vuelo = red[B].publicar("beto", "en vuelo")
    privada = red[B].publicar("beto", "privada", "followers")
    red.hacer(A, red[A].dejar_de_seguir("ana", "@beto@beta.local"))
    red.hacer(B, en_vuelo)
    red.hacer(B, privada)
    assert red[A].linea_inicio("ana") == []
    assert red[A].estado()["publicaciones"] == 1  # la privada no se guarda


def test_solicitud_pendiente_no_ve_solo_seguidores(red):
    red[B].registrar_usuario("bea", "Bea", protegida=True)
    seguir(red, A, "ana", "@bea@beta.local")
    resultado = red[B].publicar("bea", "privada", "followers")
    assert resultado.entregas == []
    assert red[A].linea_inicio("ana") == []


def test_actividad_de_un_dominio_que_no_es_el_remitente_es_invalida(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    create = red[B].publicar("beto", "hola").entregas[0].actividad
    with pytest.raises(ActividadInvalida):
        red[A].procesar(create, G)


def test_delete_de_publicacion_ajena_es_invalido(red):
    red[B].registrar_usuario("bea", "Bea")
    seguir(red, A, "ana", "@beto@beta.local")
    publicacion = red.hacer(B, red[B].publicar("beto", "hola"))
    with pytest.raises(ActividadInvalida):
        red[A].procesar(act.crear_delete("https://beta.local/users/bea", publicacion.uri), B)


def test_announce_de_solo_seguidores_es_invalido(ana_sigue_a_beto):
    red = ana_sigue_a_beto
    seguir(red, A, "ana", "@caro@gamma.local")
    privada = red.hacer(B, red[B].publicar("beto", "privada", "followers"))
    announce = {
        "id": "https://gamma.local/activities/x",
        "type": "Announce",
        "actor": CARO,
        "published": "2026-11-20T15:00:00Z",
        "object": privada.uri,
    }
    with pytest.raises(ActividadInvalida):
        red[A].procesar(announce, G)


# --- Actores remotos ---


def test_cache_de_actor_remoto(red):
    persona = red[B].servir_actor(BETO)
    actor = red[A].guardar_actor_remoto(persona, B)
    assert actor.nombre == "Beto" and actor.handle == "@beto@beta.local"
    assert red[A].perfil("@beto@beta.local")["nombre"] == "Beto"
    assert red[B].servir_actor("https://beta.local/users/nadie") is None
    with pytest.raises(ActividadInvalida):
        red[A].guardar_actor_remoto(persona, G)


def test_valores_devueltos_sobreviven_a_pickle(cadena):
    """Ray copia los valores entre actores serializándolos."""
    red, publicacion, _ = cadena
    linea = red[G].linea_inicio("caro")
    assert pickle.loads(pickle.dumps(linea)) == linea
    resultado = red[B].publicar("beto", "otra")
    assert pickle.loads(pickle.dumps(resultado)).entregas == resultado.entregas
