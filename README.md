# Blue Jay

Red social federada de micropublicaciones. Varios servidores administrados de forma independiente que permiten a sus usuarios seguirse, publicar mensajes cortos, republicar y ver líneas de tiempo, aunque estén alojados en servidores distintos.

## Objetivo

Construir un servicio de micropublicaciones con:

- Identidades de usuario en servidores independientes.
- Relaciones dirigidas de seguimiento.
- Publicaciones cortas y republicaciones.
- Líneas de tiempo con una semántica de visibilidad documentada.
- Controles de privacidad.
- Interacción entre usuarios de servidores diferentes (federación).
- Manejo definido de cambios remotos, eliminaciones y desconexiones temporales.
- Análisis de los compromisos entre disponibilidad, retardo de propagación y consistencia.

## Referencias

- [ActivityPub (W3C)](https://www.w3.org/TR/activitypub/): estándar abierto de federación entre servidores sociales.
- [Mastodon](https://docs.joinmastodon.org/): implementación desplegada de micropublicaciones federadas sobre ActivityPub.
- Twitter/X: comparación funcional histórica (sin reutilizar su marca).


## Desarrollo

Requisitos: [uv](https://docs.astral.sh/uv/). `uv` descarga Python 3.12 si hace falta.

```bash
uv sync             # crea .venv e instala las dependencias
uv run pytest       # corre las pruebas
uv run ruff check   # lint
```
