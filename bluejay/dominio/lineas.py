"""Líneas de tiempo (docs/visibilidad.md, secciones 3 a 6).

- **Inicio**: se materializa al escribir (*fan-out on write*, D8). Cuando llega una
  publicación o republicación, el servidor la agrega a la línea de cada usuario local que
  deba verla; leer el inicio no recorre el grafo de seguimientos. Encaja con una carga de
  "mucha lectura" como la de un *feed* (Conf. 1).
- **Perfil**: se arma al leer, filtrando lo que este servidor conoce del usuario según quién
  mira (`visibilidad.puede_ver`).

Cada publicación aparece **una sola vez** en el inicio aunque llegue por varios caminos (la
publicación misma y una o más republicaciones). Por cada publicación se guardan sus
*motivos* en orden de llegada y se muestra el primero (D10). Quitar un motivo (deshacer una
republicación, dejar de seguir) deja ver el siguiente, si queda alguno.

El orden es de **presentación**: hora del origen y URI como desempate (D9). No expresa
causalidad (Conf. 6); la dependencia republicación → original la garantiza el servidor al no
insertar una republicación sin su original (D12).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from bluejay.dominio.modelos import Publicacion, Republicacion


@dataclass(frozen=True, slots=True)
class ElementoLinea:
    """Un elemento visible de una línea: una publicación, quizá traída por una republicación."""

    publicacion: Publicacion
    republicacion: Republicacion | None = None

    @property
    def clave_orden(self) -> tuple[datetime, str]:
        """Una republicación se ordena por cuándo se republicó, no por el original (D9)."""
        if self.republicacion is not None:
            return self.republicacion.clave_orden
        return self.publicacion.clave_orden

    @property
    def mostrada_por(self) -> str:
        """URI del actor por el que aparece: el autor o quien republicó."""
        if self.republicacion is not None:
            return self.republicacion.actor
        return self.publicacion.autor


def ordenar(elementos: Iterable[ElementoLinea], limite: int | None = None) -> list[ElementoLinea]:
    """De la más reciente a la más antigua (D9)."""
    ordenados = sorted(elementos, key=lambda e: e.clave_orden, reverse=True)
    return ordenados if limite is None else ordenados[: max(limite, 0)]


@dataclass(frozen=True, slots=True)
class _Motivo:
    """Por qué una publicación está en un inicio."""

    actor: str  # el autor (llegó la publicación) o quien la republicó
    republicacion: Republicacion | None = None


class LineaInicio:
    """Línea de inicio de un usuario local, materializada al escribir (D8).

    Guarda referencias (URIs y republicaciones), no copias de las publicaciones: el
    contenido se busca en el almacén del servidor al leer. Así, eliminar una publicación del
    almacén basta para que deje de mostrarse aunque una línea todavía la referencie.
    """

    def __init__(self) -> None:
        # URI de la publicación -> motivos en orden de llegada (dict conserva el orden).
        self._entradas: dict[str, list[_Motivo]] = {}

    def __len__(self) -> int:
        return len(self._entradas)

    def __contains__(self, uri_publicacion: object) -> bool:
        return uri_publicacion in self._entradas

    def agregar_publicacion(self, publicacion: Publicacion) -> None:
        """Llegó la publicación de alguien a quien el usuario sigue (o la propia)."""
        self._agregar(publicacion.uri, _Motivo(actor=publicacion.autor))

    def agregar_republicacion(self, republicacion: Republicacion) -> None:
        """Llegó una republicación hecha por alguien a quien el usuario sigue (o la propia)."""
        self._agregar(
            republicacion.publicacion,
            _Motivo(actor=republicacion.actor, republicacion=republicacion),
        )

    def _agregar(self, uri_publicacion: str, motivo: _Motivo) -> None:
        motivos = self._entradas.setdefault(uri_publicacion, [])
        if motivo not in motivos:  # idempotente ante reintentos (D7)
            motivos.append(motivo)

    def quitar_publicacion(self, uri_publicacion: str) -> None:
        """La publicación se eliminó: se va con todas sus republicaciones (D13)."""
        self._entradas.pop(uri_publicacion, None)

    def quitar_republicacion(self, uri_publicacion: str, uri_republicacion: str) -> None:
        """Se deshizo una republicación. Si quedan otros motivos, la publicación sigue."""
        self._filtrar(
            uri_publicacion,
            lambda m: m.republicacion is None or m.republicacion.uri != uri_republicacion,
        )

    def quitar_actor(self, actor: str) -> None:
        """El usuario dejó de seguir a `actor`: se quitan sus publicaciones y republicaciones.

        Lo que el usuario recibió por otro camino (la republicación de un tercero al que
        sigue) se conserva (D11).
        """
        for uri in list(self._entradas):
            self._filtrar(uri, lambda m: m.actor != actor)

    def _filtrar(self, uri_publicacion: str, conservar) -> None:
        motivos = self._entradas.get(uri_publicacion)
        if motivos is None:
            return
        restantes = [m for m in motivos if conservar(m)]
        if restantes:
            self._entradas[uri_publicacion] = restantes
        else:
            del self._entradas[uri_publicacion]

    def elementos(
        self, publicaciones: Mapping[str, Publicacion], limite: int | None = None
    ) -> list[ElementoLinea]:
        """Elementos visibles, ordenados (D9). Cada publicación, con su primer motivo (D10)."""
        visibles = []
        for uri, motivos in self._entradas.items():
            publicacion = publicaciones.get(uri)
            if publicacion is None:  # eliminada o todavía no guardada
                continue
            visibles.append(ElementoLinea(publicacion, motivos[0].republicacion))
        return ordenar(visibles, limite)
