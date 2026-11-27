"""API web sobre `BackendLocal` (núcleos en el mismo proceso, sin Ray)."""

import pytest
from fastapi.testclient import TestClient

from bluejay.web.app import crear_app

ANA = "https://alpha.local/users/ana"


@pytest.fixture
def api():
    with TestClient(crear_app()) as cliente:  # `with` ejecuta la semilla (lifespan)
        yield cliente


def contenidos(respuesta):
    assert respuesta.status_code == 200, respuesta.text
    return [e["contenido"] for e in respuesta.json()]


def test_servidores(api):
    servidores = api.get("/api/servidores").json()
    assert [s["dominio"] for s in servidores] == ["alpha.local", "beta.local", "gamma.local"]
    assert all(s["online"] for s in servidores)


def test_usuarios_del_servidor(api):
    usuarios = api.get("/api/alpha.local/usuarios").json()
    assert [u["handle"] for u in usuarios] == ["@ana@alpha.local", "@dani@alpha.local"]


def buscar(elementos, contenido):
    return next(e for e in elementos if e["contenido"] == contenido)


def test_inicio_de_ana_con_la_semilla(api):
    inicio = api.get("/api/alpha.local/usuarios/ana/inicio").json()
    # "Hola" llegó primero como publicación de Beto: aunque Ana la republique después,
    # aparece una sola vez y con el primer motivo (D10), en su lugar cronológico (D9).
    assert [e["contenido"] for e in inicio] == [
        "Probando Blue Jay desde alpha",
        "Esto solo lo ven mis seguidores",
        "Hola desde beta 👋",
    ]
    hola = buscar(inicio, "Hola desde beta 👋")
    assert hola["autor"] == {
        "uri": "https://beta.local/users/beto",
        "handle": "@beto@beta.local",
        "nombre": "Beto",
    }
    assert hola["republicacion"] is None
    privada = buscar(inicio, "Esto solo lo ven mis seguidores")
    assert privada["visibilidad"] == "followers" and not privada["republicable"]


def test_la_republicacion_de_ana_esta_en_su_perfil(api):
    perfil = api.get("/api/alpha.local/perfiles/@ana@alpha.local/publicaciones").json()
    assert perfil[0]["contenido"] == "Hola desde beta 👋"
    assert perfil[0]["republicacion"]["actor"]["handle"] == "@ana@alpha.local"


def test_caro_ve_la_republicacion_en_gamma(api):
    inicio = api.get("/api/gamma.local/usuarios/caro/inicio").json()
    assert [e["contenido"] for e in inicio] == [
        "Hola desde beta 👋",
        "Probando Blue Jay desde alpha",
    ]
    assert inicio[0]["autor"]["nombre"] == "Beto"  # pedido a beta (obtener_actor)


def test_perfil_remoto_filtrado_por_observador(api):
    ruta = "/api/alpha.local/perfiles/@beto@beta.local"
    assert len(contenidos(api.get(f"{ruta}/publicaciones", params={"visto_por": "ana"}))) == 2
    assert contenidos(api.get(f"{ruta}/publicaciones", params={"visto_por": "dani"})) == [
        "Hola desde beta 👋"
    ]
    perfil = api.get(ruta, params={"visto_por": "ana"}).json()
    assert perfil["nombre"] == "Beto" and perfil["relacion"] == "accepted"


def test_publicar_y_llegar_a_los_seguidores(api):
    r = api.post(
        "/api/alpha.local/usuarios/ana/publicaciones",
        json={"texto": "nuevo", "visibilidad": "public"},
    )
    assert r.status_code == 201
    assert r.json()["autor"]["handle"] == "@ana@alpha.local"
    assert contenidos(api.get("/api/gamma.local/usuarios/caro/inicio"))[0] == "nuevo"
    assert contenidos(api.get("/api/alpha.local/usuarios/dani/inicio"))[0] == "nuevo"


def test_republicar_y_deshacer(api):
    inicio = api.get("/api/alpha.local/usuarios/ana/inicio").json()
    uri = buscar(inicio, "Probando Blue Jay desde alpha")["uri"]
    assert (
        api.post("/api/gamma.local/usuarios/caro/republicar", json={"uri": uri}).status_code == 200
    )
    api.post("/api/gamma.local/usuarios/caro/deshacer-republicacion", json={"uri": uri})
    assert contenidos(api.get("/api/gamma.local/perfiles/caro@gamma.local/publicaciones")) == []


def test_eliminar_se_propaga(api):
    uri = api.get("/api/beta.local/perfiles/@beto@beta.local/publicaciones").json()[-1]["uri"]
    assert api.post("/api/beta.local/usuarios/beto/eliminar", json={"uri": uri}).status_code == 200
    assert "Hola desde beta 👋" not in contenidos(api.get("/api/alpha.local/usuarios/ana/inicio"))
    assert "Hola desde beta 👋" not in contenidos(api.get("/api/gamma.local/usuarios/caro/inicio"))


def test_seguir_cuenta_protegida_remota_y_aceptar(api):
    r = api.post("/api/gamma.local/usuarios/caro/seguir", json={"handle": "@beto@beta.local"})
    assert r.json()["estado"] == "pending"
    pendientes = api.get("/api/beta.local/usuarios/beto/solicitudes").json()
    assert pendientes == [
        {"uri": "https://gamma.local/users/caro", "handle": "@caro@gamma.local", "nombre": "Caro"}
    ]
    api.post("/api/beta.local/usuarios/beto/aceptar", json={"handle": "@caro@gamma.local"})
    assert api.get("/api/beta.local/usuarios/beto/solicitudes").json() == []
    siguiendo = api.get("/api/gamma.local/usuarios/caro/siguiendo").json()
    assert "@beto@beta.local" in [a["handle"] for a in siguiendo]


def test_rechazar_y_dejar_de_seguir(api):
    api.post("/api/gamma.local/usuarios/caro/seguir", json={"handle": "beto@beta.local"})
    api.post("/api/beta.local/usuarios/beto/rechazar", json={"handle": "@caro@gamma.local"})
    perfil = api.get("/api/gamma.local/perfiles/@beto@beta.local", params={"visto_por": "caro"})
    assert perfil.json()["relacion"] is None

    api.post("/api/alpha.local/usuarios/ana/dejar-de-seguir", json={"handle": "@beto@beta.local"})
    assert [a["handle"] for a in api.get("/api/beta.local/usuarios/beto/seguidores").json()] == []


def test_registrar_usuario(api):
    r = api.post("/api/gamma.local/usuarios", json={"username": "gus", "nombre": "Gus"})
    assert r.status_code == 201 and r.json()["handle"] == "@gus@gamma.local"
    assert (
        api.post("/api/gamma.local/usuarios", json={"username": "gus", "nombre": "X"}).status_code
        == 400
    )


def test_desconectar_retener_y_converger(api):
    """D14: gamma desconectado, Ana publica, gamma vuelve y Caro la ve."""
    assert api.put("/api/servidores/gamma.local/conexion", json={"online": False}).json() == {
        "dominio": "gamma.local",
        "online": False,
    }
    api.post("/api/alpha.local/usuarios/ana/publicaciones", json={"texto": "mientras tanto"})
    alpha = api.get("/api/servidores/alpha.local").json()
    assert [(p["destino"], p["tipo"]) for p in alpha["pendientes"]] == [("gamma.local", "Create")]
    # Las operaciones locales de gamma siguen funcionando.
    assert "mientras tanto" not in contenidos(api.get("/api/gamma.local/usuarios/caro/inicio"))

    api.put("/api/servidores/gamma.local/conexion", json={"online": True})
    assert api.get("/api/servidores/alpha.local").json()["pendientes"] == []
    assert contenidos(api.get("/api/gamma.local/usuarios/caro/inicio"))[0] == "mientras tanto"


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo", "estado"),
    [
        ("get", "/api/delta.local/usuarios", None, 404),
        ("get", "/api/alpha.local/usuarios/nadie/inicio", None, 404),
        ("post", "/api/alpha.local/usuarios/ana/publicaciones", {"texto": "x" * 501}, 400),
        ("post", "/api/alpha.local/usuarios/ana/publicaciones", {"texto": "   "}, 400),
        (
            "post",
            "/api/alpha.local/usuarios/ana/publicaciones",
            {"texto": "a", "visibilidad": "x"},
            422,
        ),
        ("post", "/api/alpha.local/usuarios/ana/seguir", {"handle": "no es un handle"}, 400),
        (
            "post",
            "/api/alpha.local/usuarios/ana/republicar",
            {"uri": "https://beta.local/posts/x"},
            404,
        ),
    ],
)
def test_errores(api, metodo, ruta, cuerpo, estado):
    respuesta = getattr(api, metodo)(ruta, **({"json": cuerpo} if cuerpo else {}))
    assert respuesta.status_code == estado, respuesta.text
    assert "detail" in respuesta.json()


def test_republicar_solo_seguidores_es_400(api):
    inicio = api.get("/api/alpha.local/usuarios/ana/inicio").json()
    privada = buscar(inicio, "Esto solo lo ven mis seguidores")
    r = api.post("/api/alpha.local/usuarios/ana/republicar", json={"uri": privada["uri"]})
    assert r.status_code == 400


def test_sirve_el_frontend(api):
    assert "<html" in api.get("/").text.lower()
    assert api.get("/static/api.js").status_code == 200
    assert api.get("/static/styles.css").status_code == 200
