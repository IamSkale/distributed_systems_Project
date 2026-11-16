"""Actividades: el contrato entre servidores (docs/arquitectura.md, sección 5).

Los servidores solo se comunican con actividades: diccionarios con la forma de un
subconjunto de ActivityPub. Este módulo las construye a partir de los modelos y valida
las que llegan de otros servidores.

Reglas del contrato:
- Solo tipos simples (str, dict): la misma actividad viaja por Ray ahora y como JSON
  por HTTP después, sin cambios (D2). Las fechas van como texto ISO 8601 en UTC.
- Todo `id` es único y es la base de la deduplicación (Conf. 4, D7).
- Compatibilidad hacia adelante: al validar se ignoran los campos desconocidos y se
  devuelve una copia normalizada solo con los conocidos (Conf. 4).
- Coherencia del remitente: el `actor` y el `id` deben pertenecer al dominio del servidor
  que entrega la actividad. No es autenticación, solo coherencia (D15).
- Lo que no cumple el contrato lanza `ActividadInvalida`. Reintentarla no la arreglaría:
  es una *poison pill* y va directo a *dead letter* (Conf. 4, D6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from bluejay.dominio.modelos import (
    Publicacion,
    Republicacion,
    Visibilidad,
    dominio_de,
    handle_desde_uri,
    uri_actividad,
)

Actividad = dict[str, Any]


class ActividadInvalida(ValueError):
    """La actividad no cumple el contrato. No se reintenta (D6)."""


class Tipo(StrEnum):
    CREATE = "Create"
    DELETE = "Delete"
    ANNOUNCE = "Announce"
    UNDO = "Undo"
    FOLLOW = "Follow"
    ACCEPT = "Accept"
    REJECT = "Reject"


NOTE = "Note"
TIPOS_DESHACIBLES = {Tipo.FOLLOW, Tipo.ANNOUNCE}


# --- Fechas ----------------------------------------------------------------------


def fecha_a_texto(valor: datetime) -> str:
    """`datetime` con zona -> `2026-11-20T15:04:05.123456Z`."""
    if valor.tzinfo is None:
        raise ValueError(f"La fecha debe tener zona horaria: {valor!r}")
    return valor.astimezone(UTC).isoformat().replace("+00:00", "Z")


def texto_a_fecha(texto: str) -> datetime:
    """Inversa de `fecha_a_texto`. Rechaza fechas sin zona horaria."""
    try:
        valor = datetime.fromisoformat(texto)
    except (TypeError, ValueError) as error:
        raise ActividadInvalida(f"Fecha inválida: {texto!r}") from error
    if valor.tzinfo is None:
        raise ActividadInvalida(f"Fecha sin zona horaria: {texto!r}")
    return valor.astimezone(UTC)


# --- Construcción ----------------------------------------------------------------


def _resumen(actividad: Actividad) -> Actividad:
    """Copia mínima de una actividad para incrustarla en `Accept`, `Reject` o `Undo`."""
    return {k: actividad[k] for k in ("id", "type", "actor", "object")}


def note(publicacion: Publicacion) -> dict[str, str]:
    """Objeto `Note` de una publicación. También es la respuesta de `obtener_objeto` (D12)."""
    return {
        "id": publicacion.uri,
        "type": NOTE,
        "attributedTo": publicacion.autor,
        "content": publicacion.contenido,
        "visibility": str(publicacion.visibilidad),
        "published": fecha_a_texto(publicacion.publicada),
    }


def crear_create(publicacion: Publicacion) -> Actividad:
    return {
        "id": uri_actividad(publicacion.dominio_origen),
        "type": str(Tipo.CREATE),
        "actor": publicacion.autor,
        "published": fecha_a_texto(publicacion.publicada),
        "object": note(publicacion),
    }


def crear_delete(actor: str, uri_publicacion: str) -> Actividad:
    return {
        "id": uri_actividad(dominio_de(actor)),
        "type": str(Tipo.DELETE),
        "actor": actor,
        "object": uri_publicacion,
    }


def crear_announce(republicacion: Republicacion) -> Actividad:
    """El `id` del `Announce` es la URI de la republicación."""
    return {
        "id": republicacion.uri,
        "type": str(Tipo.ANNOUNCE),
        "actor": republicacion.actor,
        "published": fecha_a_texto(republicacion.publicada),
        "object": republicacion.publicacion,
    }


def crear_follow(seguidor: str, seguido: str) -> Actividad:
    """El `id` resultante se guarda en `Seguimiento.actividad`."""
    return {
        "id": uri_actividad(dominio_de(seguidor)),
        "type": str(Tipo.FOLLOW),
        "actor": seguidor,
        "object": seguido,
    }


def crear_accept(follow: Actividad) -> Actividad:
    """Lo envía el seguido: acepta el `Follow` incrustado."""
    return _respuesta_a_follow(Tipo.ACCEPT, follow)


def crear_reject(follow: Actividad) -> Actividad:
    """Lo envía el seguido: rechaza el `Follow` incrustado."""
    return _respuesta_a_follow(Tipo.REJECT, follow)


def _respuesta_a_follow(tipo: Tipo, follow: Actividad) -> Actividad:
    seguido = follow["object"]
    return {
        "id": uri_actividad(dominio_de(seguido)),
        "type": str(tipo),
        "actor": seguido,
        "object": _resumen(follow),
    }


def crear_undo(actividad: Actividad) -> Actividad:
    """Deshace un `Follow` (dejar de seguir) o un `Announce` (deshacer republicación)."""
    if actividad["type"] not in TIPOS_DESHACIBLES:
        raise ValueError(f"No se puede deshacer una actividad {actividad['type']!r}")
    actor = actividad["actor"]
    return {
        "id": uri_actividad(dominio_de(actor)),
        "type": str(Tipo.UNDO),
        "actor": actor,
        "object": _resumen(actividad),
    }


# --- Validación de lo recibido ----------------------------------------------------


def _texto(contenedor: dict[str, Any], campo: str) -> str:
    valor = contenedor.get(campo)
    if not isinstance(valor, str) or not valor:
        raise ActividadInvalida(f"Falta el campo {campo!r} o no es texto")
    return valor


def _uri(contenedor: dict[str, Any], campo: str) -> str:
    valor = _texto(contenedor, campo)
    try:
        dominio_de(valor)
    except ValueError as error:
        raise ActividadInvalida(f"{campo!r} no es una URI: {valor!r}") from error
    return valor


def _uri_actor(contenedor: dict[str, Any], campo: str) -> str:
    valor = _texto(contenedor, campo)
    try:
        handle_desde_uri(valor)
    except ValueError as error:
        raise ActividadInvalida(f"{campo!r} no es la URI de un actor: {valor!r}") from error
    return valor


def _fecha(contenedor: dict[str, Any], campo: str) -> str:
    """Valida la fecha y la devuelve normalizada a UTC."""
    return fecha_a_texto(texto_a_fecha(_texto(contenedor, campo)))


def _objeto_dict(actividad: Actividad) -> dict[str, Any]:
    objeto = actividad.get("object")
    if not isinstance(objeto, dict):
        raise ActividadInvalida("El campo 'object' debe ser un objeto")
    return objeto


def _exigir_mismo_dominio(uri: str, dominio: str, que: str) -> None:
    if dominio_de(uri) != dominio:
        raise ActividadInvalida(f"{que} {uri!r} no pertenece a {dominio!r}")


def validar_note(objeto: Any, dominio_origen: str) -> dict[str, str]:
    """Valida un `Note` recibido de `dominio_origen` (en un `Create` o en `obtener_objeto`)."""
    if not isinstance(objeto, dict) or objeto.get("type") != NOTE:
        raise ActividadInvalida("Se esperaba un objeto de tipo 'Note'")
    uri = _uri(objeto, "id")
    autor = _uri_actor(objeto, "attributedTo")
    _exigir_mismo_dominio(uri, dominio_origen, "La publicación")
    _exigir_mismo_dominio(autor, dominio_origen, "El autor")
    contenido = objeto.get("content")
    if not isinstance(contenido, str):
        raise ActividadInvalida("El campo 'content' debe ser texto")
    try:
        visibilidad = Visibilidad(objeto.get("visibility"))
    except ValueError as error:
        raise ActividadInvalida(f"Visibilidad desconocida: {objeto.get('visibility')!r}") from error
    return {
        "id": uri,
        "type": NOTE,
        "attributedTo": autor,
        "content": contenido,
        "visibility": str(visibilidad),
        "published": _fecha(objeto, "published"),
    }


def _validar_create(actividad: Actividad, base: Actividad) -> Actividad:
    objeto = validar_note(_objeto_dict(actividad), dominio_de(base["actor"]))
    if objeto["attributedTo"] != base["actor"]:
        raise ActividadInvalida("El autor de la publicación no es quien envía el Create")
    return {**base, "published": objeto["published"], "object": objeto}


def _validar_delete(actividad: Actividad, base: Actividad) -> Actividad:
    objeto = actividad.get("object")
    if isinstance(objeto, dict):  # ActivityPub también admite el objeto incrustado
        objeto = objeto.get("id")
    uri = _uri({"object": objeto}, "object")
    _exigir_mismo_dominio(
        uri, dominio_de(base["actor"]), "Solo se pueden eliminar objetos propios:"
    )
    return {**base, "object": uri}


def _validar_announce(actividad: Actividad, base: Actividad) -> Actividad:
    # El original puede ser de cualquier servidor (republicar contenido ajeno).
    return {
        **base,
        "published": _fecha(actividad, "published"),
        "object": _uri(actividad, "object"),
    }


def _validar_follow(actividad: Actividad, base: Actividad) -> Actividad:
    seguido = _uri_actor(actividad, "object")
    if seguido == base["actor"]:
        raise ActividadInvalida("Un usuario no puede seguirse a sí mismo")
    return {**base, "object": seguido}


def _validar_follow_incrustado(objeto: dict[str, Any]) -> Actividad:
    if objeto.get("type") != Tipo.FOLLOW:
        raise ActividadInvalida("Se esperaba un 'Follow' incrustado")
    return {
        "id": _uri(objeto, "id"),
        "type": str(Tipo.FOLLOW),
        "actor": _uri_actor(objeto, "actor"),
        "object": _uri_actor(objeto, "object"),
    }


def _validar_respuesta(actividad: Actividad, base: Actividad) -> Actividad:
    follow = _validar_follow_incrustado(_objeto_dict(actividad))
    if follow["object"] != base["actor"]:
        raise ActividadInvalida("Solo el usuario seguido puede aceptar o rechazar el Follow")
    return {**base, "object": follow}


def _validar_undo(actividad: Actividad, base: Actividad) -> Actividad:
    objeto = _objeto_dict(actividad)
    tipo = objeto.get("type")
    if tipo == Tipo.FOLLOW:
        deshecha = _validar_follow_incrustado(objeto)
    elif tipo == Tipo.ANNOUNCE:
        deshecha = {
            "id": _uri(objeto, "id"),
            "type": str(Tipo.ANNOUNCE),
            "actor": _uri_actor(objeto, "actor"),
            "object": _uri(objeto, "object"),
        }
    else:
        raise ActividadInvalida(f"No se puede deshacer una actividad {tipo!r}")
    if deshecha["actor"] != base["actor"]:
        raise ActividadInvalida("Solo quien hizo la actividad puede deshacerla")
    return {**base, "object": deshecha}


_VALIDADORES = {
    Tipo.CREATE: _validar_create,
    Tipo.DELETE: _validar_delete,
    Tipo.ANNOUNCE: _validar_announce,
    Tipo.FOLLOW: _validar_follow,
    Tipo.ACCEPT: _validar_respuesta,
    Tipo.REJECT: _validar_respuesta,
    Tipo.UNDO: _validar_undo,
}


def validar(actividad: Any, dominio_remitente: str) -> Actividad:
    """Valida una actividad entregada por `dominio_remitente`.

    Devuelve una copia normalizada que contiene solo los campos conocidos. Lanza
    `ActividadInvalida` si no cumple el contrato.
    """
    if not isinstance(actividad, dict):
        raise ActividadInvalida("La actividad debe ser un objeto")
    try:
        tipo = Tipo(actividad.get("type"))
    except ValueError as error:
        raise ActividadInvalida(
            f"Tipo de actividad desconocido: {actividad.get('type')!r}"
        ) from error

    base = {
        "id": _uri(actividad, "id"),
        "type": str(tipo),
        "actor": _uri_actor(actividad, "actor"),
    }
    _exigir_mismo_dominio(base["actor"], dominio_remitente, "El actor")
    _exigir_mismo_dominio(base["id"], dominio_remitente, "La actividad")
    return _VALIDADORES[tipo](actividad, base)


# --- Conversión a modelos ---------------------------------------------------------


def publicacion_desde_note(objeto: dict[str, str]) -> Publicacion:
    """`Note` ya validado -> `Publicacion` (copia local; `recibida` es ahora)."""
    return Publicacion(
        uri=objeto["id"],
        autor=objeto["attributedTo"],
        contenido=objeto["content"],
        visibilidad=Visibilidad(objeto["visibility"]),
        publicada=texto_a_fecha(objeto["published"]),
    )


def republicacion_desde_announce(actividad: Actividad) -> Republicacion:
    """`Announce` ya validado -> `Republicacion`."""
    return Republicacion(
        uri=actividad["id"],
        actor=actividad["actor"],
        publicacion=actividad["object"],
        publicada=texto_a_fecha(actividad["published"]),
    )
