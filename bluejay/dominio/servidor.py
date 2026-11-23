"""`ServidorBlueJay`: el estado y la lógica de un servidor federado.

Python puro, sin Ray ni red (D2). Cada operación actualiza el estado local y **devuelve las
entregas que hay que hacer** (`Entrega(dominio_destino, actividad)`) en vez de enviarlas:
el transporte (actores de Ray ahora, HTTP después) las encola y las entrega con reintentos
(D6). Por eso este núcleo se prueba conectando dos instancias a mano, sin levantar Ray.

Tipos de métodos:
- **API local** (`publicar`, `seguir`, ...): lo que hacen los usuarios de este servidor. Las
  que pueden generar actividades devuelven un `Resultado` (valor + entregas).
- **Federación** (`procesar`, `servir_objeto`, `recibir_objeto`, ...): lo que llega de otros
  servidores o se les responde.
- **Lectura** (`linea_inicio`, `linea_perfil`, `perfil`, ...): no cambian nada.

Garantías que implementa (docs/visibilidad.md, sección 7):
- *Read-your-writes* local: lo propio entra en las líneas locales antes de devolver las
  entregas.
- Efecto *exactly-once*: deduplicación por ID de actividad y *handlers* idempotentes por sí
  mismos (D7, Conf. 4).
- Una republicación nunca se muestra antes que su original: espera por dependencia (D12,
  consistencia causal de Conf. 6).
- Una eliminación gana sobre un `Create` atrasado gracias al *tombstone* (D13, Conf. 5).

Cada método es atómico respecto del estado: no espera nada externo en el medio. La regla
"volver a verificar tras un `await`" (D17) la cumple la capa de Ray llamando de nuevo al
núcleo, que siempre decide con el estado actual (por ejemplo, `recibir_objeto` descarta un
original que ya nadie espera).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bluejay.dominio import actividades as act
from bluejay.dominio.actividades import Actividad, ActividadInvalida, Tipo
from bluejay.dominio.lineas import ElementoLinea, LineaInicio, ordenar
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
    ahora,
    dominio_de,
    handle_desde_uri,
    parsear_handle,
    uri_actividad,
    uri_actor,
    uri_desde_handle,
    uri_publicacion,
    validar_dominio,
)
from bluejay.dominio.visibilidad import destinos, puede_ver, servidor_puede_ver

LIMITE_CARACTERES = 500


class ErrorOperacion(ValueError):
    """Un usuario local pidió algo que no se puede hacer (texto muy largo, etc.)."""


class NoEncontrado(LookupError):
    """El usuario o la publicación no existe en este servidor (o el usuario no puede verla)."""


@dataclass(slots=True)
class Resultado[T]:
    """Lo que devuelve una operación: su valor y las entregas pendientes (D2)."""

    valor: T
    entregas: list[Entrega] = field(default_factory=list)


class ServidorBlueJay:
    """Estado en memoria de un servidor (D3) y sus operaciones."""

    def __init__(self, dominio: str, limite_caracteres: int = LIMITE_CARACTERES) -> None:
        self.dominio = validar_dominio(dominio)
        self.limite_caracteres = limite_caracteres

        # Identidades
        self._usuarios: dict[str, Usuario] = {}  # username -> usuario local
        self._actores_remotos: dict[str, ActorRemoto] = {}  # URI -> copia en caché

        # Contenido: propio y copias de otros servidores
        self._publicaciones: dict[str, Publicacion] = {}
        self._republicaciones: dict[str, Republicacion] = {}
        self._tombstones: dict[str, Tombstone] = {}

        # Grafo de seguimientos que conoce este servidor: (seguidor, seguido) -> relación.
        # Un seguimiento local se guarda una vez; uno remoto, en ambos servidores.
        self._seguimientos: dict[tuple[str, str], Seguimiento] = {}

        # Líneas de inicio materializadas (D8)
        self._inicio: dict[str, LineaInicio] = {}  # username -> línea

        # Federación
        self._procesadas: set[str] = set()  # IDs de actividades ya aplicadas (D7)
        self._pendientes: dict[str, list[Republicacion]] = {}  # original -> Announce (D12)
        self._enviada_a: dict[str, set[str]] = {}  # URI propia -> servidores con copia (D13)

    # --- Utilidades -----------------------------------------------------------------

    def _es_local(self, uri: str) -> bool:
        return dominio_de(uri) == self.dominio

    def _usuario(self, username: str) -> Usuario:
        try:
            return self._usuarios[username]
        except KeyError:
            raise NoEncontrado(f"No existe el usuario {username!r} en {self.dominio}") from None

    def _usuario_de_uri(self, uri: str) -> Usuario | None:
        if not self._es_local(uri):
            return None
        try:
            username, _ = parsear_handle(handle_desde_uri(uri))
        except ValueError:
            return None
        return self._usuarios.get(username)

    def _observador(self, visto_por: str | None) -> str | None:
        return None if visto_por is None else self._usuario(visto_por).uri

    def _seguimientos_de(self, seguido: str, estado: EstadoSeguimiento) -> list[Seguimiento]:
        return sorted(
            (s for s in self._seguimientos.values() if s.seguido == seguido and s.estado == estado),
            key=lambda s: s.creado,
        )

    def _seguidores_aceptados(self, actor: str) -> list[str]:
        return [s.seguidor for s in self._seguimientos_de(actor, EstadoSeguimiento.ACEPTADO)]

    def _puede_ver(self, publicacion: Publicacion, observador: str | None) -> bool:
        return puede_ver(publicacion, observador, self._seguidores_aceptados(publicacion.autor))

    def _destinos(self, actor: str) -> list[str]:
        """Servidores con al menos un seguidor aceptado de `actor` (D5)."""
        return sorted(destinos(self._seguidores_aceptados(actor), self.dominio))

    def _receptores(self, actor: str) -> list[str]:
        """Usuarios locales en cuyo inicio entra lo que hace `actor`: él mismo y sus
        seguidores aceptados locales (docs/visibilidad.md, sección 3)."""
        receptores = []
        propio = self._usuario_de_uri(actor)
        if propio is not None:
            receptores.append(propio.username)
        for seguidor in self._seguidores_aceptados(actor):
            local = self._usuario_de_uri(seguidor)
            if local is not None:
                receptores.append(local.username)
        return receptores

    @staticmethod
    def _follow(seguimiento: Seguimiento) -> Actividad:
        """Reconstruye el `Follow` de un seguimiento remoto (para `Accept`, `Reject`, `Undo`)."""
        return {
            "id": seguimiento.actividad,
            "type": str(Tipo.FOLLOW),
            "actor": seguimiento.seguidor,
            "object": seguimiento.seguido,
        }

    @staticmethod
    def _entregas(dominios: list[str] | set[str], actividad: Actividad) -> list[Entrega]:
        return [Entrega(destino, actividad) for destino in sorted(dominios)]

    # --- Cambios de estado compartidos por la API local y la federación ---------------

    def _repartir_publicacion(self, publicacion: Publicacion) -> None:
        """*Fan-out* al escribir (D8)."""
        for username in self._receptores(publicacion.autor):
            if self._puede_ver(publicacion, uri_actor(self.dominio, username)):
                self._inicio[username].agregar_publicacion(publicacion)

    def _repartir_republicacion(self, republicacion: Republicacion) -> None:
        publicacion = self._publicaciones[republicacion.publicacion]
        for username in self._receptores(republicacion.actor):
            if self._puede_ver(publicacion, uri_actor(self.dominio, username)):
                self._inicio[username].agregar_republicacion(republicacion)

    def _guardar_publicacion(self, publicacion: Publicacion) -> None:
        """Guarda una publicación y libera las republicaciones que la esperaban (D12)."""
        self._publicaciones[publicacion.uri] = publicacion
        self._repartir_publicacion(publicacion)
        for republicacion in self._pendientes.pop(publicacion.uri, []):
            self._guardar_republicacion(republicacion)

    def _guardar_republicacion(self, republicacion: Republicacion) -> None:
        """Precondición: el original está guardado (D12)."""
        if republicacion.uri in self._republicaciones:
            return
        if not self._publicaciones[republicacion.publicacion].es_republicable:
            return  # una "solo seguidores" no se republica (docs/visibilidad.md)
        self._republicaciones[republicacion.uri] = republicacion
        self._repartir_republicacion(republicacion)

    def _quitar_republicacion(self, republicacion: Republicacion) -> None:
        self._republicaciones.pop(republicacion.uri, None)
        for linea in self._inicio.values():
            linea.quitar_republicacion(republicacion.publicacion, republicacion.uri)

    def _borrar_publicacion(self, uri: str) -> None:
        """Borra la publicación (si la hay) y deja el *tombstone* (D13).

        Funciona aunque la publicación todavía no haya llegado: el *tombstone* hace que
        un `Create` atrasado se ignore (`Delete` antes que `Create`).
        """
        self._publicaciones.pop(uri, None)
        self._tombstones.setdefault(uri, Tombstone(uri))
        self._pendientes.pop(uri, None)
        for republicacion in [r for r in self._republicaciones.values() if r.publicacion == uri]:
            self._republicaciones.pop(republicacion.uri)
            self._enviada_a.pop(republicacion.uri, None)
        for linea in self._inicio.values():
            linea.quitar_publicacion(uri)

    def _republicacion_de(self, actor: str, uri_publicacion: str) -> Republicacion | None:
        for republicacion in self._republicaciones.values():
            if republicacion.actor == actor and republicacion.publicacion == uri_publicacion:
                return republicacion
        return None

    # --- API local: usuarios -------------------------------------------------------

    def registrar_usuario(self, username: str, nombre: str, protegida: bool = False) -> Usuario:
        """No genera actividades: los demás servidores conocen al usuario al seguirlo."""
        if username in self._usuarios:
            raise ErrorOperacion(f"El usuario {username!r} ya existe en {self.dominio}")
        usuario = Usuario(
            username=username, dominio=self.dominio, nombre=nombre, protegida=protegida
        )
        self._usuarios[username] = usuario
        self._inicio[username] = LineaInicio()
        return usuario

    # --- API local: publicaciones -----------------------------------------------------

    def publicar(
        self, username: str, texto: str, visibilidad: Visibilidad | str = Visibilidad.PUBLICA
    ) -> Resultado[Publicacion]:
        """Crea la publicación, la pone en las líneas locales y devuelve un `Create` por
        cada servidor con seguidores aceptados (D4, D5)."""
        usuario = self._usuario(username)
        if not texto.strip():
            raise ErrorOperacion("La publicación no puede estar vacía")
        if len(texto) > self.limite_caracteres:
            raise ErrorOperacion(
                f"La publicación tiene {len(texto)} caracteres; el límite es "
                f"{self.limite_caracteres}"
            )
        publicacion = Publicacion(
            uri=uri_publicacion(self.dominio),
            autor=usuario.uri,
            contenido=texto,
            visibilidad=Visibilidad(visibilidad),
            publicada=ahora(),
        )
        self._guardar_publicacion(publicacion)
        enviar_a = self._destinos(usuario.uri)
        self._enviada_a[publicacion.uri] = set(enviar_a)
        return Resultado(publicacion, self._entregas(enviar_a, act.crear_create(publicacion)))

    def eliminar(self, username: str, uri: str) -> Resultado[None]:
        """Borra una publicación propia y envía `Delete` a todos los servidores que la
        recibieron o la pidieron (D13). Eliminar dos veces no tiene efecto."""
        usuario = self._usuario(username)
        if uri in self._tombstones:
            return Resultado(None)
        publicacion = self._publicaciones.get(uri)
        if publicacion is None or publicacion.autor != usuario.uri:
            raise NoEncontrado(f"{usuario.handle} no tiene una publicación {uri!r}")
        self._borrar_publicacion(uri)
        enviar_a = self._enviada_a.pop(uri, set())
        return Resultado(None, self._entregas(enviar_a, act.crear_delete(usuario.uri, uri)))

    def republicar(self, username: str, uri: str) -> Resultado[Republicacion]:
        """Republica una publicación pública que este servidor conoce. Es idempotente."""
        usuario = self._usuario(username)
        publicacion = self._publicaciones.get(uri)
        if publicacion is None or not self._puede_ver(publicacion, usuario.uri):
            raise NoEncontrado(f"No se conoce la publicación {uri!r}")
        if not publicacion.es_republicable:
            raise ErrorOperacion("Solo se pueden republicar publicaciones públicas")
        existente = self._republicacion_de(usuario.uri, uri)
        if existente is not None:
            return Resultado(existente)
        republicacion = Republicacion(
            uri=uri_actividad(self.dominio),
            actor=usuario.uri,
            publicacion=uri,
            publicada=ahora(),
        )
        self._guardar_republicacion(republicacion)
        enviar_a = self._destinos(usuario.uri)
        self._enviada_a[republicacion.uri] = set(enviar_a)
        return Resultado(republicacion, self._entregas(enviar_a, act.crear_announce(republicacion)))

    def deshacer_republicacion(self, username: str, uri: str) -> Resultado[None]:
        """Envía `Undo(Announce)` a donde se envió el `Announce`. Es idempotente."""
        usuario = self._usuario(username)
        republicacion = self._republicacion_de(usuario.uri, uri)
        if republicacion is None:
            return Resultado(None)
        self._quitar_republicacion(republicacion)
        enviar_a = self._enviada_a.pop(republicacion.uri, set())
        undo = act.crear_undo(act.crear_announce(republicacion))
        return Resultado(None, self._entregas(enviar_a, undo))

    # --- API local: seguimiento -------------------------------------------------------

    def seguir(self, username: str, handle: str) -> Resultado[Seguimiento]:
        """Seguir a un usuario local se resuelve aquí mismo. Seguir a uno remoto genera un
        `Follow` y queda `pending` hasta que llegue el `Accept` (docs/arquitectura.md, 4.2).

        Si ya hay un seguimiento (pendiente o aceptado), no hace nada.
        """
        usuario = self._usuario(username)
        seguido = uri_desde_handle(handle)
        existente = self._seguimientos.get((usuario.uri, seguido))
        if existente is not None:
            return Resultado(existente)

        if self._es_local(seguido):
            destino = self._usuario_de_uri(seguido)
            if destino is None:
                raise NoEncontrado(f"No existe el usuario {handle!r}")
            estado = (
                EstadoSeguimiento.PENDIENTE if destino.protegida else EstadoSeguimiento.ACEPTADO
            )
            seguimiento = Seguimiento(usuario.uri, seguido, estado)
            self._seguimientos[(usuario.uri, seguido)] = seguimiento
            return Resultado(seguimiento)

        follow = act.crear_follow(usuario.uri, seguido)
        seguimiento = Seguimiento(usuario.uri, seguido, actividad=follow["id"])
        self._seguimientos[(usuario.uri, seguido)] = seguimiento
        return Resultado(seguimiento, [Entrega(dominio_de(seguido), follow)])

    def dejar_de_seguir(self, username: str, handle: str) -> Resultado[None]:
        """Quita del inicio todo lo que llegó por esa persona (D11) y, si es remota, envía
        `Undo(Follow)`. También cancela una solicitud pendiente."""
        usuario = self._usuario(username)
        seguido = uri_desde_handle(handle)
        seguimiento = self._seguimientos.pop((usuario.uri, seguido), None)
        if seguimiento is None:
            return Resultado(None)
        self._inicio[username].quitar_actor(seguido)
        if self._es_local(seguido):
            return Resultado(None)
        undo = act.crear_undo(self._follow(seguimiento))
        return Resultado(None, [Entrega(dominio_de(seguido), undo)])

    def solicitudes(self, username: str) -> list[str]:
        """URIs de quienes pidieron seguir a `username` y esperan respuesta."""
        usuario = self._usuario(username)
        return [s.seguidor for s in self._seguimientos_de(usuario.uri, EstadoSeguimiento.PENDIENTE)]

    def seguidores(self, username: str) -> list[str]:
        return self._seguidores_aceptados(self._usuario(username).uri)

    def siguiendo(self, username: str) -> list[str]:
        uri = self._usuario(username).uri
        return [
            s.seguido
            for s in sorted(self._seguimientos.values(), key=lambda s: s.creado)
            if s.seguidor == uri and s.aceptado
        ]

    def aceptar(self, username: str, seguidor: str) -> Resultado[Seguimiento]:
        """Acepta una solicitud pendiente. Si el seguidor es remoto, le envía `Accept`."""
        usuario = self._usuario(username)
        seguimiento = self._seguimientos.get((seguidor, usuario.uri))
        if seguimiento is None:
            raise NoEncontrado(f"{seguidor!r} no pidió seguir a {usuario.handle}")
        if seguimiento.aceptado:
            return Resultado(seguimiento)
        seguimiento.aceptar()
        if self._es_local(seguidor):
            return Resultado(seguimiento)
        accept = act.crear_accept(self._follow(seguimiento))
        return Resultado(seguimiento, [Entrega(dominio_de(seguidor), accept)])

    def rechazar(self, username: str, seguidor: str) -> Resultado[None]:
        """Rechaza una solicitud pendiente: el seguimiento se borra (puede volver a pedirse)."""
        usuario = self._usuario(username)
        seguimiento = self._seguimientos.get((seguidor, usuario.uri))
        if seguimiento is None:
            return Resultado(None)
        if seguimiento.aceptado:
            raise ErrorOperacion("Solo se pueden rechazar solicitudes pendientes")
        del self._seguimientos[(seguidor, usuario.uri)]
        if self._es_local(seguidor):
            return Resultado(None)
        reject = act.crear_reject(self._follow(seguimiento))
        return Resultado(None, [Entrega(dominio_de(seguidor), reject)])

    # --- Lectura ------------------------------------------------------------------

    def linea_inicio(self, username: str, limite: int = 20) -> list[ElementoLinea]:
        self._usuario(username)
        return self._inicio[username].elementos(self._publicaciones, limite)

    def linea_perfil(
        self, handle: str, visto_por: str | None = None, limite: int = 20
    ) -> list[ElementoLinea]:
        """Publicaciones y republicaciones de `handle` que este servidor conoce, filtradas
        según quién mira (docs/visibilidad.md, sección 4). De un usuario remoto puede estar
        incompleta: es una vista local y parcial."""
        actor = uri_desde_handle(handle)
        if self._es_local(actor) and self._usuario_de_uri(actor) is None:
            raise NoEncontrado(f"No existe el usuario {handle!r}")
        observador = self._observador(visto_por)
        elementos = [
            ElementoLinea(p)
            for p in self._publicaciones.values()
            if p.autor == actor and self._puede_ver(p, observador)
        ]
        for republicacion in self._republicaciones.values():
            if republicacion.actor != actor:
                continue
            original = self._publicaciones.get(republicacion.publicacion)
            if original is not None and self._puede_ver(original, observador):
                elementos.append(ElementoLinea(original, republicacion))
        return ordenar(elementos, limite)

    def perfil(self, handle: str, visto_por: str | None = None) -> dict[str, Any]:
        """Datos del usuario. De un remoto, los de la caché si la hay (`nombre` puede ser None)."""
        actor = uri_desde_handle(handle)
        observador = self._observador(visto_por)
        local = self._usuario_de_uri(actor)
        if self._es_local(actor) and local is None:
            raise NoEncontrado(f"No existe el usuario {handle!r}")
        remoto = self._actores_remotos.get(actor)
        relacion = self._seguimientos.get((observador, actor)) if observador else None
        return {
            "uri": actor,
            "handle": handle_desde_uri(actor),
            "local": local is not None,
            "nombre": local.nombre if local else (remoto.nombre if remoto else None),
            "protegida": local.protegida if local else (remoto.protegida if remoto else None),
            "seguidores": len(self._seguidores_aceptados(actor)) if local else None,
            "siguiendo": len(self.siguiendo(local.username)) if local else None,
            "relacion": str(relacion.estado) if relacion else None,
        }

    def usuarios(self, visto_por: str | None = None) -> list[dict[str, Any]]:
        """Perfiles de los usuarios de este servidor, por orden de registro."""
        ordenados = sorted(self._usuarios.values(), key=lambda u: u.creado)
        return [self.perfil(u.handle, visto_por) for u in ordenados]

    def nombres(self, uris: list[str]) -> dict[str, str | None]:
        """Nombre visible de cada actor: el local, el de la caché, o `None` si no se conoce.

        Una sola llamada para toda una línea de tiempo (en Ray, un solo viaje al actor).
        """
        resultado: dict[str, str | None] = {}
        for uri in uris:
            local = self._usuario_de_uri(uri)
            remoto = self._actores_remotos.get(uri)
            resultado[uri] = local.nombre if local else (remoto.nombre if remoto else None)
        return resultado

    # --- Federación: actividades recibidas -----------------------------------------

    def procesar(self, actividad: Any, dominio_remitente: str) -> list[Entrega]:
        """Aplica una actividad entregada por `dominio_remitente` (el `inbox`).

        - Inválida: lanza `ActividadInvalida`; el entregador no la reintenta (D6).
        - Ya procesada: no hace nada (deduplicación, D7).
        - Devuelve las entregas que genere (solo un `Follow` genera un `Accept`).
        """
        actividad = act.validar(actividad, dominio_remitente)
        if actividad["id"] in self._procesadas:
            return []
        entregas = self._MANEJADORES[Tipo(actividad["type"])](self, actividad)
        self._procesadas.add(actividad["id"])
        return entregas

    def _procesar_create(self, actividad: Actividad) -> list[Entrega]:
        uri = actividad["object"]["id"]
        if uri in self._tombstones or uri in self._publicaciones:
            return []  # Delete antes que Create (D13) o duplicado (D7)
        publicacion = act.publicacion_desde_note(actividad["object"])
        if publicacion.visibilidad is Visibilidad.SEGUIDORES and not self._receptores(
            publicacion.autor
        ):
            # Nadie aquí la puede ver (p. ej., llegó después de un Undo(Follow), D11): no se
            # guarda contenido privado que ningún usuario local tiene derecho a leer.
            return []
        self._guardar_publicacion(publicacion)
        return []

    def _procesar_announce(self, actividad: Actividad) -> list[Entrega]:
        republicacion = act.republicacion_desde_announce(actividad)
        if (
            republicacion.uri in self._republicaciones
            or republicacion.publicacion in self._tombstones
        ):
            return []
        if not self._receptores(republicacion.actor):
            return []  # ningún usuario local sigue a quien republica (p. ej., D11)
        original = self._publicaciones.get(republicacion.publicacion)
        if original is None:
            # Se acepta y queda esperando a su original (D12). La capa de transporte lo pide
            # con `obtener_objeto` (ver `dependencias_pendientes`).
            esperando = self._pendientes.setdefault(republicacion.publicacion, [])
            if republicacion not in esperando:
                esperando.append(republicacion)
            return []
        if not original.es_republicable:
            raise ActividadInvalida("No se puede republicar una publicación 'solo seguidores'")
        self._guardar_republicacion(republicacion)
        return []

    def _procesar_delete(self, actividad: Actividad) -> list[Entrega]:
        uri = actividad["object"]
        publicacion = self._publicaciones.get(uri)
        if publicacion is not None and publicacion.autor != actividad["actor"]:
            raise ActividadInvalida("Solo el autor puede eliminar la publicación")
        self._borrar_publicacion(uri)
        return []

    def _procesar_undo(self, actividad: Actividad) -> list[Entrega]:
        deshecha = actividad["object"]
        # Si la actividad deshecha llegara más tarde (reordenada), ya no tendrá efecto.
        self._procesadas.add(deshecha["id"])
        if deshecha["type"] == Tipo.FOLLOW:
            clave = (deshecha["actor"], deshecha["object"])
            seguimiento = self._seguimientos.get(clave)
            if seguimiento is not None and seguimiento.actividad == deshecha["id"]:
                del self._seguimientos[clave]
        else:  # Announce
            republicacion = self._republicaciones.get(deshecha["id"])
            if republicacion is not None:
                self._quitar_republicacion(republicacion)
            esperando = self._pendientes.get(deshecha["object"], [])
            esperando[:] = [r for r in esperando if r.uri != deshecha["id"]]
            if not esperando:
                self._pendientes.pop(deshecha["object"], None)
        return []

    def _procesar_follow(self, actividad: Actividad) -> list[Entrega]:
        seguido = self._usuario_de_uri(actividad["object"])
        if seguido is None:
            # Reintentar no lo arreglaría: va a dead letter (D6).
            raise ActividadInvalida(
                f"No existe el usuario {actividad['object']!r} en {self.dominio}"
            )
        clave = (actividad["actor"], seguido.uri)
        seguimiento = self._seguimientos.get(clave)
        if seguimiento is None:
            seguimiento = Seguimiento(actividad["actor"], seguido.uri, actividad=actividad["id"])
            self._seguimientos[clave] = seguimiento
        else:
            seguimiento.actividad = actividad["id"]  # nueva solicitud del mismo seguidor
        if not seguido.protegida:
            seguimiento.aceptar()
        if seguimiento.aceptado:
            return [Entrega(dominio_de(actividad["actor"]), act.crear_accept(actividad))]
        return []  # cuenta protegida: espera a `aceptar` o `rechazar`

    def _procesar_accept(self, actividad: Actividad) -> list[Entrega]:
        seguimiento = self._seguimiento_de_respuesta(actividad)
        if seguimiento is not None:
            seguimiento.aceptar()
        return []

    def _procesar_reject(self, actividad: Actividad) -> list[Entrega]:
        seguimiento = self._seguimiento_de_respuesta(actividad)
        if seguimiento is not None:
            del self._seguimientos[(seguimiento.seguidor, seguimiento.seguido)]
            local = self._usuario_de_uri(seguimiento.seguidor)
            if local is not None:
                self._inicio[local.username].quitar_actor(seguimiento.seguido)
        return []

    def _seguimiento_de_respuesta(self, actividad: Actividad) -> Seguimiento | None:
        """El seguimiento al que responde un `Accept`/`Reject`, solo si es el del mismo
        `Follow`: una respuesta a una solicitud vieja (ya deshecha) se ignora."""
        follow = actividad["object"]
        seguimiento = self._seguimientos.get((follow["actor"], follow["object"]))
        if seguimiento is None or seguimiento.actividad != follow["id"]:
            return None
        return seguimiento

    _MANEJADORES: dict[Tipo, Callable[[ServidorBlueJay, Actividad], list[Entrega]]] = {
        Tipo.CREATE: _procesar_create,
        Tipo.ANNOUNCE: _procesar_announce,
        Tipo.DELETE: _procesar_delete,
        Tipo.UNDO: _procesar_undo,
        Tipo.FOLLOW: _procesar_follow,
        Tipo.ACCEPT: _procesar_accept,
        Tipo.REJECT: _procesar_reject,
    }

    # --- Federación: obtener objetos y actores (pull, D12) --------------------------

    def servir_objeto(self, uri: str, dominio_solicitante: str) -> dict[str, Any] | None:
        """Respuesta de `obtener_objeto`: una publicación propia, si el servidor que la
        pide puede verla. Registra al solicitante para enviarle el `Delete` (D13).

        Devuelve un `Tombstone` si se eliminó y `None` si no existe o no puede verla.
        """
        if not self._es_local(uri):
            return None  # solo el origen es fuente de verdad
        if uri in self._tombstones:
            return act.tombstone(uri)
        publicacion = self._publicaciones.get(uri)
        if publicacion is None:
            return None
        seguidores = self._seguidores_aceptados(publicacion.autor)
        if not servidor_puede_ver(publicacion, dominio_solicitante, seguidores):
            return None
        if dominio_solicitante != self.dominio:
            self._enviada_a.setdefault(uri, set()).add(dominio_solicitante)
        return act.note(publicacion)

    def dependencias_pendientes(self) -> list[str]:
        """Originales que hay que pedir con `obtener_objeto` (D12)."""
        return list(self._pendientes)

    def recibir_objeto(self, objeto: Any, dominio_origen: str) -> None:
        """Guarda un original obtenido de su origen y libera las republicaciones que lo
        esperaban (D12). Si ya nadie lo espera (por ejemplo, llegó un `Undo` mientras se
        pedía), se descarta: se decide con el estado actual, no con el de antes (D17)."""
        objeto = act.validar_objeto(objeto, dominio_origen)
        uri = objeto["id"]
        if objeto["type"] == act.TOMBSTONE:
            self._borrar_publicacion(uri)
            return
        if uri not in self._pendientes or uri in self._tombstones or uri in self._publicaciones:
            return
        self._guardar_publicacion(act.publicacion_desde_note(objeto))

    def descartar_dependencia(self, uri: str) -> None:
        """El origen respondió que el original no existe o no es visible: se abandonan
        las republicaciones que lo esperaban."""
        self._pendientes.pop(uri, None)

    def servir_actor(self, uri: str) -> dict[str, Any] | None:
        """Respuesta de `obtener_actor`: el `Person` de un usuario local."""
        usuario = self._usuario_de_uri(uri)
        return None if usuario is None else act.persona(usuario)

    def guardar_actor_remoto(self, objeto: Any, dominio_origen: str) -> ActorRemoto:
        """Guarda (o renueva) la copia en caché de un actor remoto."""
        actor = act.actor_remoto_desde_persona(act.validar_persona(objeto, dominio_origen))
        self._actores_remotos[actor.uri] = actor
        return actor

    # --- Observabilidad -------------------------------------------------------------

    def estado(self) -> dict[str, Any]:
        return {
            "dominio": self.dominio,
            "usuarios": len(self._usuarios),
            "actores_remotos": len(self._actores_remotos),
            "publicaciones": len(self._publicaciones),
            "republicaciones": len(self._republicaciones),
            "tombstones": len(self._tombstones),
            "seguimientos": len(self._seguimientos),
            "actividades_procesadas": len(self._procesadas),
            "dependencias_pendientes": sum(len(r) for r in self._pendientes.values()),
        }
