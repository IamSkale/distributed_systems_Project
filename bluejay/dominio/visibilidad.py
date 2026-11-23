"""Reglas de visibilidad (docs/visibilidad.md).

Funciones puras: reciben lo que el servidor sabe (quiénes son seguidores aceptados) y
responden quién puede ver una publicación y a qué servidores se envía. La regla de
privacidad se aplica en los dos extremos (docs/visibilidad.md, sección 2):

- **al enviar**: `destinos` nunca incluye un servidor sin seguidores aceptados del autor;
- **al leer**: `puede_ver` filtra por observador.

Un seguimiento `pending` no cuenta como seguidor para ningún efecto.
"""

from __future__ import annotations

from collections.abc import Iterable

from bluejay.dominio.modelos import Publicacion, Visibilidad, dominio_de


def puede_ver(
    publicacion: Publicacion,
    observador: str | None,
    seguidores_aceptados: Iterable[str],
) -> bool:
    """¿Puede `observador` (URI de un actor, o `None` si es anónimo) ver la publicación?

    `seguidores_aceptados` son las URIs de los seguidores aceptados del autor que conoce
    este servidor. Cada servidor solo conoce su parte del grafo: en un receptor basta con
    saber si el observador local sigue al autor (docs/visibilidad.md, sección 4).
    """
    if publicacion.visibilidad is Visibilidad.PUBLICA:
        return True
    if observador is None:
        return False
    return observador == publicacion.autor or observador in set(seguidores_aceptados)


def destinos(seguidores_aceptados: Iterable[str], dominio_local: str) -> set[str]:
    """Servidores remotos a los que se envía una publicación o republicación.

    Una sola entrega por servidor con al menos un seguidor aceptado, no una por seguidor
    (*shared inbox*, D5). Vale igual para "pública" y "solo seguidores": ninguna sale hacia
    un servidor donde el autor no tenga seguidores aceptados (docs/visibilidad.md,
    sección 2). El receptor calcula después a qué usuarios locales le llega.
    """
    return {dominio_de(uri) for uri in seguidores_aceptados} - {dominio_local}


def servidor_puede_ver(
    publicacion: Publicacion, dominio: str, seguidores_aceptados: Iterable[str]
) -> bool:
    """¿Puede el servidor `dominio` obtener la publicación con `obtener_objeto` (D12)?

    Es la misma regla que `destinos`: una "solo seguidores" solo se entrega a servidores
    donde el autor tiene seguidores aceptados. Pedirla no abre una puerta trasera.
    """
    if publicacion.visibilidad is Visibilidad.PUBLICA:
        return True
    return dominio in {dominio_de(uri) for uri in seguidores_aceptados}
