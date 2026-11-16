"""Modelos del dominio de Blue Jay.

Datos puros, sin Ray ni red (decisión D2): el mismo núcleo sirve para la versión con
Ray (Entrega 1) y para la versión HTTP (entrega final).

Convenciones:
- Identidad: actores, publicaciones y actividades se identifican con URIs con forma de
  URL (`https://alpha.local/users/ana`). El dominio de la URI es su servidor de origen,
  que es la fuente de verdad de ese dato; los demás servidores guardan copias (cachés).
- Tiempo: todas las fechas son `datetime` con zona horaria (UTC). Son horas de pared:
  sirven para presentar y medir, no para decidir qué ocurrió antes (Conf. 6, D9).
- Inmutabilidad: lo que no cambia después de crearse (publicaciones, republicaciones,
  tombstones, entregas) es `frozen`. Ray copia los objetos entre actores serializándolos,
  así que todos los modelos deben sobrevivir a `pickle`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[a-z0-9_]{1,30}$")
DOMINIO_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
HANDLE_RE = re.compile(r"^@?(?P<username>[^@\s]+)@(?P<dominio>[^@\s]+)$")


class Visibilidad(StrEnum):
    """Niveles de visibilidad de la Entrega 1 (docs/visibilidad.md)."""

    PUBLICA = "public"
    SEGUIDORES = "followers"


class EstadoSeguimiento(StrEnum):
    PENDIENTE = "pending"
    ACEPTADO = "accepted"


# --- Utilidades: fechas, validación e identificadores ---------------------------


def ahora() -> datetime:
    return datetime.now(UTC)


def validar_username(username: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            f"Nombre de usuario inválido: {username!r}. "
            "Solo se permiten minúsculas, números y '_' (de 1 a 30 caracteres)."
        )
    return username


def validar_dominio(dominio: str) -> str:
    if not DOMINIO_RE.fullmatch(dominio):
        raise ValueError(f"Dominio inválido: {dominio!r}")
    return dominio


def _exigir_zona_horaria(nombre: str, valor: datetime) -> None:
    # Comparar fechas con y sin zona horaria lanza TypeError y rompería el orden.
    if valor.tzinfo is None:
        raise ValueError(f"{nombre} debe tener zona horaria (usar UTC), se recibió {valor!r}")


def uri_actor(dominio: str, username: str) -> str:
    return f"https://{validar_dominio(dominio)}/users/{validar_username(username)}"


def uri_publicacion(dominio: str) -> str:
    """URI nueva y única para una publicación creada en `dominio`."""
    return f"https://{validar_dominio(dominio)}/posts/{uuid.uuid4()}"


def uri_actividad(dominio: str) -> str:
    """URI nueva y única para una actividad de `dominio`.

    Es el identificador que permite deduplicar reintentos (Conf. 4, D7).
    """
    return f"https://{validar_dominio(dominio)}/activities/{uuid.uuid4()}"


def dominio_de(uri: str) -> str:
    """Servidor de origen de una URI: `https://beta.local/posts/x` -> `beta.local`."""
    dominio = urlparse(uri).hostname
    if not dominio:
        raise ValueError(f"URI sin dominio: {uri!r}")
    return dominio


def parsear_handle(handle: str) -> tuple[str, str]:
    """`@ana@alpha.local` (o `ana@alpha.local`) -> (`ana`, `alpha.local`)."""
    coincidencia = HANDLE_RE.fullmatch(handle.strip())
    if not coincidencia:
        raise ValueError(f"Handle inválido: {handle!r}. Formato esperado: @usuario@servidor")
    username = validar_username(coincidencia["username"])
    dominio = validar_dominio(coincidencia["dominio"])
    return username, dominio


def uri_desde_handle(handle: str) -> str:
    username, dominio = parsear_handle(handle)
    return uri_actor(dominio, username)


def handle_desde_uri(uri: str) -> str:
    """`https://alpha.local/users/ana` -> `@ana@alpha.local`."""
    partes = urlparse(uri)
    segmentos = partes.path.strip("/").split("/")
    if len(segmentos) != 2 or segmentos[0] != "users" or not partes.hostname:
        raise ValueError(f"No es la URI de un actor: {uri!r}")
    return f"@{segmentos[1]}@{partes.hostname}"


# --- Actores ---------------------------------------------------------------------


@dataclass(slots=True)
class Usuario:
    """Usuario alojado en este servidor: aquí está su fuente de verdad."""

    username: str
    dominio: str
    nombre: str
    protegida: bool = False  # cuenta protegida: los seguimientos requieren aprobación
    creado: datetime = field(default_factory=ahora)

    def __post_init__(self) -> None:
        validar_username(self.username)
        validar_dominio(self.dominio)
        _exigir_zona_horaria("creado", self.creado)

    @property
    def uri(self) -> str:
        return uri_actor(self.dominio, self.username)

    @property
    def handle(self) -> str:
        return f"@{self.username}@{self.dominio}"


@dataclass(slots=True)
class ActorRemoto:
    """Copia en caché de un actor de otro servidor.

    La fuente de verdad está en su origen; `obtenido` indica la antigüedad de la copia.
    """

    uri: str
    nombre: str
    protegida: bool = False
    obtenido: datetime = field(default_factory=ahora)

    def __post_init__(self) -> None:
        handle_desde_uri(self.uri)  # valida que sea la URI de un actor
        _exigir_zona_horaria("obtenido", self.obtenido)

    @property
    def dominio(self) -> str:
        return dominio_de(self.uri)

    @property
    def handle(self) -> str:
        return handle_desde_uri(self.uri)


# --- Contenido -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Publicacion:
    """Publicación propia o copia recibida de otro servidor.

    El límite de caracteres no se valida aquí, sino al publicar localmente: una
    publicación remota puede venir de un servidor con otro límite.
    """

    uri: str
    autor: str  # URI del actor
    contenido: str
    visibilidad: Visibilidad
    publicada: datetime  # hora de pared del origen: orden de presentación (D9)
    recibida: datetime = field(default_factory=ahora)  # llegada a este servidor (retardo)

    def __post_init__(self) -> None:
        # Acepta "public"/"followers" como texto; un valor desconocido falla.
        object.__setattr__(self, "visibilidad", Visibilidad(self.visibilidad))
        _exigir_zona_horaria("publicada", self.publicada)
        _exigir_zona_horaria("recibida", self.recibida)
        dominio_de(self.uri)
        handle_desde_uri(self.autor)

    @property
    def dominio_origen(self) -> str:
        return dominio_de(self.uri)

    @property
    def es_republicable(self) -> bool:
        """Solo las publicaciones públicas se pueden republicar (docs/visibilidad.md)."""
        return self.visibilidad is Visibilidad.PUBLICA

    @property
    def clave_orden(self) -> tuple[datetime, str]:
        """Hora del origen y, si empatan, la URI (D9). No expresa causalidad (Conf. 6)."""
        return (self.publicada, self.uri)


@dataclass(frozen=True, slots=True)
class Republicacion:
    """Republicación (`Announce`) de una publicación, propia o ajena.

    Su URI es el ID de la actividad `Announce`, como en ActivityPub. Depende
    causalmente de su original: no se muestra antes que él (Conf. 6, D12).
    """

    uri: str
    actor: str  # quién republica
    publicacion: str  # URI de la publicación republicada
    publicada: datetime
    recibida: datetime = field(default_factory=ahora)

    def __post_init__(self) -> None:
        _exigir_zona_horaria("publicada", self.publicada)
        _exigir_zona_horaria("recibida", self.recibida)
        dominio_de(self.uri)
        dominio_de(self.publicacion)
        handle_desde_uri(self.actor)

    @property
    def clave_orden(self) -> tuple[datetime, str]:
        return (self.publicada, self.uri)


@dataclass(frozen=True, slots=True)
class Tombstone:
    """Marca de una publicación eliminada (D13).

    Hace que un `Create` atrasado no la "resucite": como la encarnación en SWIM, la
    información más nueva gana sobre un rumor tardío (Conf. 5).
    """

    uri: str
    eliminada: datetime = field(default_factory=ahora)

    def __post_init__(self) -> None:
        dominio_de(self.uri)
        _exigir_zona_horaria("eliminada", self.eliminada)


# --- Relaciones ------------------------------------------------------------------


@dataclass(slots=True)
class Seguimiento:
    """Relación dirigida: `seguidor` sigue a `seguido` (no implica lo contrario)."""

    seguidor: str  # URI del actor que sigue
    seguido: str  # URI del actor seguido
    estado: EstadoSeguimiento = EstadoSeguimiento.PENDIENTE
    actividad: str | None = None  # ID del `Follow`; lo referencian `Accept`, `Reject` y `Undo`
    creado: datetime = field(default_factory=ahora)

    def __post_init__(self) -> None:
        handle_desde_uri(self.seguidor)
        handle_desde_uri(self.seguido)
        if self.seguidor == self.seguido:
            raise ValueError("Un usuario no puede seguirse a sí mismo")
        self.estado = EstadoSeguimiento(self.estado)
        _exigir_zona_horaria("creado", self.creado)

    @property
    def aceptado(self) -> bool:
        return self.estado is EstadoSeguimiento.ACEPTADO

    def aceptar(self) -> None:
        self.estado = EstadoSeguimiento.ACEPTADO


# --- Comunicación entre servidores -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Entrega:
    """Una actividad que hay que entregar a un servidor destino.

    Es lo que el núcleo devuelve en vez de enviar nada por sí mismo (D2): el
    transporte (Ray ahora, HTTP después) la encola y la entrega con reintentos (D6).
    Hay una sola entrega por servidor destino, no una por destinatario (D5).
    """

    destino: str  # dominio del servidor destino
    actividad: dict[str, Any] = field(hash=False)

    def __post_init__(self) -> None:
        validar_dominio(self.destino)
        for campo in ("id", "type", "actor"):
            if campo not in self.actividad:
                raise ValueError(f"La actividad no tiene el campo obligatorio {campo!r}")

    @property
    def id_actividad(self) -> str:
        return self.actividad["id"]
