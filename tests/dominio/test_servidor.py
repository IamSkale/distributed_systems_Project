"""Operaciones locales de `ServidorBlueJay` (un solo servidor, sin federación)."""

import pytest

from bluejay.dominio.modelos import EstadoSeguimiento
from bluejay.dominio.servidor import ErrorOperacion, NoEncontrado, ServidorBlueJay

ANA = "https://alpha.local/users/ana"
DANI = "https://alpha.local/users/dani"
EVA = "https://alpha.local/users/eva"


@pytest.fixture
def alpha():
    servidor = ServidorBlueJay("alpha.local", limite_caracteres=20)
    servidor.registrar_usuario("ana", "Ana")
    servidor.registrar_usuario("dani", "Dani")
    servidor.registrar_usuario("eva", "Eva", protegida=True)
    return servidor


def uris(elementos):
    return [e.publicacion.uri for e in elementos]


# --- Usuarios ---


def test_nombre_de_usuario_unico_por_servidor(alpha):
    with pytest.raises(ErrorOperacion):
        alpha.registrar_usuario("ana", "Otra Ana")


def test_nombre_de_usuario_con_caracteres_no_permitidos(alpha):
    with pytest.raises(ValueError):
        alpha.registrar_usuario("Ana!", "Ana")


def test_usuario_inexistente(alpha):
    with pytest.raises(NoEncontrado):
        alpha.publicar("nadie", "hola")
    with pytest.raises(NoEncontrado):
        alpha.linea_perfil("@nadie@alpha.local")


# --- Publicar ---


def test_publicar_aparece_en_inicio_y_perfil_del_autor(alpha):
    """Leer lo propio (docs/visibilidad.md, sección 7)."""
    resultado = alpha.publicar("ana", "hola")
    assert resultado.entregas == []  # sin seguidores remotos no sale nada
    assert uris(alpha.linea_inicio("ana")) == [resultado.valor.uri]
    assert uris(alpha.linea_perfil("@ana@alpha.local")) == [resultado.valor.uri]


def test_limite_de_caracteres(alpha):
    alpha.publicar("ana", "x" * 20)
    with pytest.raises(ErrorOperacion):
        alpha.publicar("ana", "x" * 21)


def test_publicacion_vacia(alpha):
    with pytest.raises(ErrorOperacion):
        alpha.publicar("ana", "   ")


def test_visibilidad_desconocida(alpha):
    with pytest.raises(ValueError):
        alpha.publicar("ana", "hola", "unlisted")


# --- Seguir localmente ---


def test_seguir_cuenta_local_publica(alpha):
    seguimiento = alpha.seguir("ana", "@dani@alpha.local").valor
    assert seguimiento.aceptado
    publicacion = alpha.publicar("dani", "hola").valor
    assert uris(alpha.linea_inicio("ana")) == [publicacion.uri]
    assert alpha.seguidores("dani") == [ANA]
    assert alpha.siguiendo("ana") == [DANI]


def test_seguir_dos_veces_no_hace_nada(alpha):
    primero = alpha.seguir("ana", "@dani@alpha.local").valor
    segundo = alpha.seguir("ana", "@dani@alpha.local")
    assert segundo.valor is primero and segundo.entregas == []


def test_no_puede_seguirse_a_si_mismo(alpha):
    with pytest.raises(ValueError):
        alpha.seguir("ana", "@ana@alpha.local")


def test_seguir_usuario_local_inexistente(alpha):
    with pytest.raises(NoEncontrado):
        alpha.seguir("ana", "@nadie@alpha.local")


def test_cuenta_protegida_pendiente_hasta_aceptar_y_sin_historial(alpha):
    antes = alpha.publicar("eva", "antes").valor
    seguimiento = alpha.seguir("ana", "@eva@alpha.local").valor
    assert seguimiento.estado is EstadoSeguimiento.PENDIENTE
    assert alpha.solicitudes("eva") == [ANA]

    alpha.publicar("eva", "pendiente")
    assert alpha.linea_inicio("ana") == []  # pendiente no recibe nada

    alpha.aceptar("eva", ANA)
    assert alpha.solicitudes("eva") == []
    despues = alpha.publicar("eva", "despues").valor
    # Solo lo nuevo: no se trae el historial (docs/visibilidad.md, sección 6).
    assert uris(alpha.linea_inicio("ana")) == [despues.uri]
    assert antes.uri not in uris(alpha.linea_inicio("ana"))


def test_rechazar_borra_la_solicitud_y_se_puede_volver_a_pedir(alpha):
    alpha.seguir("ana", "@eva@alpha.local")
    alpha.rechazar("eva", ANA)
    assert alpha.solicitudes("eva") == []
    assert alpha.seguir("ana", "@eva@alpha.local").valor.estado is EstadoSeguimiento.PENDIENTE


def test_no_se_rechaza_un_seguidor_ya_aceptado(alpha):
    alpha.seguir("ana", "@dani@alpha.local")
    with pytest.raises(ErrorOperacion):
        alpha.rechazar("dani", ANA)


def test_aceptar_solicitud_inexistente(alpha):
    with pytest.raises(NoEncontrado):
        alpha.aceptar("eva", ANA)


def test_dejar_de_seguir_quita_sus_publicaciones_del_inicio(alpha):
    """D11."""
    alpha.seguir("ana", "@dani@alpha.local")
    alpha.publicar("dani", "hola")
    alpha.dejar_de_seguir("ana", "@dani@alpha.local")
    assert alpha.linea_inicio("ana") == []
    alpha.publicar("dani", "despues")
    assert alpha.linea_inicio("ana") == []


def test_dejar_de_seguir_cancela_solicitud_pendiente(alpha):
    alpha.seguir("ana", "@eva@alpha.local")
    alpha.dejar_de_seguir("ana", "@eva@alpha.local")
    assert alpha.solicitudes("eva") == []


# --- Visibilidad "solo seguidores" (docs/visibilidad.md, secciones 2 y 4) ---


@pytest.fixture
def con_privada(alpha):
    """Eva (protegida) publica "solo seguidores"; Ana la sigue, Dani tiene solicitud
    pendiente."""
    alpha.seguir("ana", "@eva@alpha.local")
    alpha.aceptar("eva", ANA)
    alpha.seguir("dani", "@eva@alpha.local")
    publica = alpha.publicar("eva", "publica").valor
    privada = alpha.publicar("eva", "privada", "followers").valor
    alpha.registrar_usuario("fede", "Fede")
    return alpha, publica, privada


@pytest.mark.parametrize(
    ("visto_por", "ve_privada"),
    [("eva", True), ("ana", True), ("dani", False), ("fede", False), (None, False)],
)
def test_perfil_filtrado_segun_observador(con_privada, visto_por, ve_privada):
    alpha, publica, privada = con_privada
    vistas = uris(alpha.linea_perfil("@eva@alpha.local", visto_por=visto_por))
    assert publica.uri in vistas
    assert (privada.uri in vistas) is ve_privada


def test_solo_seguidores_en_inicio_de_seguidores_aceptados(con_privada):
    alpha, publica, privada = con_privada
    assert set(uris(alpha.linea_inicio("ana"))) == {privada.uri, publica.uri}
    assert alpha.linea_inicio("dani") == []


# --- Republicar ---


def test_republicar_llega_a_los_seguidores_de_quien_republica(alpha):
    alpha.seguir("dani", "@ana@alpha.local")
    publicacion = alpha.publicar("eva", "hola").valor
    republicacion = alpha.republicar("ana", publicacion.uri).valor
    inicio_dani = alpha.linea_inicio("dani")
    assert [(e.publicacion.uri, e.mostrada_por) for e in inicio_dani] == [(publicacion.uri, ANA)]
    perfil_ana = alpha.linea_perfil("@ana@alpha.local")
    assert perfil_ana[0].republicacion == republicacion


def test_republicar_dos_veces_es_idempotente(alpha):
    publicacion = alpha.publicar("dani", "hola").valor
    primera = alpha.republicar("ana", publicacion.uri).valor
    assert alpha.republicar("ana", publicacion.uri).valor is primera


def test_no_se_republica_solo_seguidores_ni_el_autor(alpha):
    privada = alpha.publicar("dani", "privada", "followers").valor
    with pytest.raises(ErrorOperacion):
        alpha.republicar("dani", privada.uri)


def test_no_se_republica_lo_que_no_se_puede_ver(alpha):
    privada = alpha.publicar("dani", "privada", "followers").valor
    with pytest.raises(NoEncontrado):
        alpha.republicar("ana", privada.uri)


def test_deshacer_republicacion(alpha):
    alpha.seguir("dani", "@ana@alpha.local")
    publicacion = alpha.publicar("eva", "hola").valor
    alpha.republicar("ana", publicacion.uri)
    alpha.deshacer_republicacion("ana", publicacion.uri)
    assert alpha.linea_inicio("dani") == []
    assert alpha.linea_perfil("@ana@alpha.local") == []
    assert alpha.deshacer_republicacion("ana", publicacion.uri).entregas == []  # idempotente


def test_dos_republicaciones_de_lo_mismo_aparecen_una_vez(alpha):
    """D10: con la etiqueta de quien republicó primero."""
    alpha.registrar_usuario("fede", "Fede")
    alpha.seguir("fede", "@ana@alpha.local")
    alpha.seguir("fede", "@dani@alpha.local")
    publicacion = alpha.publicar("eva", "hola").valor
    alpha.republicar("ana", publicacion.uri)
    alpha.republicar("dani", publicacion.uri)
    inicio = alpha.linea_inicio("fede")
    assert [(e.publicacion.uri, e.mostrada_por) for e in inicio] == [(publicacion.uri, ANA)]


# --- Eliminar ---


def test_eliminar_quita_de_lineas_y_republicaciones(alpha):
    """D13."""
    alpha.seguir("ana", "@dani@alpha.local")
    alpha.seguir("eva", "@ana@alpha.local")
    publicacion = alpha.publicar("dani", "hola").valor
    alpha.republicar("ana", publicacion.uri)
    alpha.eliminar("dani", publicacion.uri)
    for usuario in ("ana", "dani", "eva"):
        assert alpha.linea_inicio(usuario) == []
    assert alpha.linea_perfil("@ana@alpha.local") == []
    with pytest.raises(NoEncontrado):
        alpha.republicar("eva", publicacion.uri)


def test_solo_el_autor_elimina(alpha):
    publicacion = alpha.publicar("dani", "hola").valor
    with pytest.raises(NoEncontrado):
        alpha.eliminar("ana", publicacion.uri)


def test_eliminar_dos_veces_no_hace_nada(alpha):
    publicacion = alpha.publicar("dani", "hola").valor
    alpha.eliminar("dani", publicacion.uri)
    assert alpha.eliminar("dani", publicacion.uri).entregas == []


# --- Perfil y estado ---


def test_perfil_local(alpha):
    alpha.seguir("ana", "@dani@alpha.local")
    alpha.seguir("dani", "@eva@alpha.local")
    datos = alpha.perfil("@dani@alpha.local", visto_por="ana")
    assert datos["nombre"] == "Dani"
    assert datos["seguidores"] == 1 and datos["siguiendo"] == 0
    assert datos["relacion"] == "accepted"
    assert alpha.perfil("@eva@alpha.local", visto_por="dani")["relacion"] == "pending"


def test_limite_de_la_linea(alpha):
    for n in range(5):
        alpha.publicar("ana", f"post {n}")
    assert len(alpha.linea_inicio("ana", limite=3)) == 3


def test_estado(alpha):
    alpha.publicar("ana", "hola")
    estado = alpha.estado()
    assert estado["usuarios"] == 3 and estado["publicaciones"] == 1
