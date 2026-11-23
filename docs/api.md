# API web (frontend)

Contrato JSON entre el frontend (`templates/`, `static/`) y el sistema. Es estable: hoy responde sobre los núcleos en un solo proceso (`BackendLocal`) y, cuando esté la capa de Ray (Etapa D), lo hará sobre los actores **sin cambiar rutas ni formatos**.

## Arranque

```bash
uv run python -m bluejay.web            # http://127.0.0.1:8000
uv run python -m bluejay.web --reload   # reinicia al cambiar el código Python
```

- `/`: el frontend (`templates/index.html`). `/static/...`: los archivos de `static/`.
- `/docs`: documentación interactiva generada por FastAPI, para probar cada ruta desde el navegador.
- Al arrancar se cargan **datos de ejemplo** (el comienzo del guion de la demo):

| Servidor | Usuarios | Relaciones y contenido |
|---|---|---|
| `alpha.local` | `ana`, `dani` | Ana sigue a Beto (aceptado); Dani sigue a Ana. Ana publicó y republicó "Hola desde beta". |
| `beta.local` | `beto` (cuenta protegida) | Una publicación pública y una "solo seguidores". |
| `gamma.local` | `caro` | Caro sigue a Ana y ve la republicación. |

- El estado está **en memoria**: al reiniciar se pierde y se vuelve a cargar la semilla.
- CORS abierto: el frontend también puede servirse desde otro servidor de desarrollo (p. ej., Live Server) apuntando a `http://127.0.0.1:8000`.

## Conceptos

- **Sin inicio de sesión** en la Entrega 1. El frontend elige **servidor** (`dominio`) y **usuario** (`username`) y los pone en la ruta. Las lecturas reciben `?visto_por=<username>` para aplicar la visibilidad (`visibilidad.md`).
- **Identificadores:** los usuarios se identifican con su *handle* `@usuario@servidor`, que también vale sin la `@` inicial o como URI (`https://alpha.local/users/ana`). Las publicaciones, con su URI (`https://beta.local/posts/<uuid>`); como contiene `/`, va siempre **en el cuerpo**, no en la ruta.
- **Fechas:** texto ISO 8601 en UTC (`2026-11-23T21:51:05.894575Z`). El frontend las formatea ("Hace 2 h").
- **Consistencia eventual:** una acción en un servidor llega a los demás después. Con `BackendLocal` es casi inmediata; con Ray habrá retardo real, así que **el frontend debe volver a pedir las líneas** (al enfocar la pestaña o cada pocos segundos) en vez de suponer que ya están al día.
- **Errores:** `{"detail": "mensaje"}` con `404` (no existe o no se puede ver), `400` (operación no permitida: texto vacío o de más de 500 caracteres, republicar algo "solo seguidores", usuario repetido…) o `422` (cuerpo mal formado).

## Formatos

**Actor**

```json
{ "uri": "https://beta.local/users/beto", "handle": "@beto@beta.local", "nombre": "Beto" }
```

`nombre` puede ser `null` si el servidor aún no conoce a ese usuario remoto: mostrar el handle.

**Elemento de línea de tiempo** (inicio y perfil)

```json
{
  "uri": "https://beta.local/posts/07ae…",
  "autor": { "uri": "…", "handle": "@beto@beta.local", "nombre": "Beto" },
  "contenido": "Hola desde beta 👋",
  "visibilidad": "public",
  "publicada": "2026-11-23T21:51:05.894575Z",
  "republicable": true,
  "republicacion": {
    "uri": "https://alpha.local/activities/0fdb…",
    "actor": { "uri": "…", "handle": "@ana@alpha.local", "nombre": "Ana" },
    "publicada": "2026-11-23T21:51:05.895107Z"
  }
}
```

- `republicacion` es `null` si el elemento es la publicación misma. Si no, mostrar "🔁 Ana republicó" arriba de la publicación.
- La lista ya viene **ordenada** (más reciente primero) y **sin duplicados**: una publicación aparece una sola vez aunque la hayan republicado varios (D10).
- `visibilidad`: `"public"` o `"followers"` (mostrar un candado). Si `republicable` es `false`, deshabilitar el botón de republicar.
- Para saber si el usuario actual puede eliminar: `autor.handle == "@<username>@<dominio>"`.

**Perfil**

```json
{
  "uri": "https://beta.local/users/beto", "handle": "@beto@beta.local", "local": true,
  "nombre": "Beto", "protegida": true, "seguidores": 1, "siguiendo": 0,
  "relacion": "accepted"
}
```

- `relacion`: cómo se relaciona `visto_por` con este usuario: `"accepted"` (lo sigue), `"pending"` (solicitud enviada) o `null`. Sirve para el botón Seguir / Solicitud enviada / Dejar de seguir.
- `seguidores` y `siguiendo` son `null` para usuarios remotos: cada servidor solo conoce su parte del grafo.

## Rutas

### Servidores

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| GET | `/api/servidores` | — | `[{"dominio", "online"}]` |
| GET | `/api/servidores/{dominio}` | — | `{"dominio", "online", "estado": {...contadores}, "pendientes": [{"destino","tipo","id"}], "dead_letters": [{"destino","tipo","id","motivo"}]}` |
| PUT | `/api/servidores/{dominio}/conexion` | `{"online": false}` | `{"dominio", "online"}` |

`conexion` simula la desconexión de un servidor (D14). Sus usuarios siguen pudiendo publicar y leer, pero no recibe ni envía actividades; las entregas quedan en `pendientes` y salen al reconectar. Es el paso 9 de la demo.

### Usuarios y perfiles

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| GET | `/api/{dominio}/usuarios?visto_por=` | — | `[Perfil]` de los usuarios de ese servidor |
| POST | `/api/{dominio}/usuarios` | `{"username", "nombre", "protegida": false}` | `201` + Perfil |
| GET | `/api/{dominio}/perfiles/{handle}?visto_por=` | — | Perfil (local o remoto) |
| GET | `/api/{dominio}/perfiles/{handle}/publicaciones?visto_por=&limite=20` | — | `[Elemento]` |

El perfil de un usuario **remoto** muestra solo lo que ese servidor conoce: puede estar incompleto (`visibilidad.md`, sección 4).

### Líneas de tiempo y publicaciones

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| GET | `/api/{dominio}/usuarios/{username}/inicio?limite=20` | — | `[Elemento]` |
| POST | `/api/{dominio}/usuarios/{username}/publicaciones` | `{"texto", "visibilidad": "public" \| "followers"}` | `201` + Elemento |
| POST | `/api/{dominio}/usuarios/{username}/eliminar` | `{"uri"}` | `{"ok": true}` |
| POST | `/api/{dominio}/usuarios/{username}/republicar` | `{"uri"}` | `{"uri", "actor", "publicada"}` |
| POST | `/api/{dominio}/usuarios/{username}/deshacer-republicacion` | `{"uri"}` (de la publicación original) | `{"ok": true}` |

### Seguimiento

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/api/{dominio}/usuarios/{username}/seguir` | `{"handle"}` | `{"seguido", "estado": "accepted" \| "pending"}` |
| POST | `/api/{dominio}/usuarios/{username}/dejar-de-seguir` | `{"handle"}` | `{"ok": true}` |
| GET | `/api/{dominio}/usuarios/{username}/solicitudes` | — | `[Actor]` pendientes de aprobar |
| POST | `/api/{dominio}/usuarios/{username}/aceptar` | `{"handle"}` del solicitante | `{"ok": true}` |
| POST | `/api/{dominio}/usuarios/{username}/rechazar` | `{"handle"}` del solicitante | `{"ok": true}` |
| GET | `/api/{dominio}/usuarios/{username}/seguidores` | — | `[Actor]` |
| GET | `/api/{dominio}/usuarios/{username}/siguiendo` | — | `[Actor]` |

Seguir a alguien **remoto** siempre empieza en `"pending"`: pasa a `"accepted"` cuando llega el `Accept` de su servidor (inmediato si la cuenta no es protegida). Ver la relación actualizada con `GET /perfiles/{handle}?visto_por=`.

## De `static/api.js` a estas rutas

`api.js` hoy devuelve datos de prueba. Esta es la correspondencia de cada función:

| Función actual | Ruta | Notas |
|---|---|---|
| `usuario_actual()` | `GET /api/{dominio}/perfiles/{handle}` | Pasa a ser un **selector** de servidor y usuario (con `GET /api/servidores` y `GET /api/{dominio}/usuarios`). |
| `linea_inicio()` | `GET …/usuarios/{username}/inicio` | Mostrar `republicacion` y el candado de `followers`. |
| `linea_perfil(usuarioId)` | `GET …/perfiles/{handle}/publicaciones?visto_por=` | El id pasa a ser el handle. |
| `publicar(contenido)` | `POST …/usuarios/{username}/publicaciones` | Añadir el selector de visibilidad. |
| `republicar(id)` | `POST …/republicar` o `…/deshacer-republicacion` | Alternar según el usuario ya la haya republicado. |
| `eliminar(id)` | `POST …/eliminar` | Solo en publicaciones propias. |
| `seguir(usuarioId)` | `POST …/seguir` y `…/dejar-de-seguir` | Usar `relacion` del perfil para el texto del botón. |
| `solicitudes_pendientes()` | `GET …/solicitudes` | |
| `aceptar(solicitudId)` | `POST …/aceptar` | Añadir **rechazar** (`POST …/rechazar`). |
| `buscar(termino)` | — | **No hay búsqueda.** Alternativa: un campo para escribir un handle (`@beto@beta.local`) y abrir su perfil. |
| `dar_me_gusta(id)` | — | **Fuera de la Entrega 1** (`plan_entrega_1.md`, sección 1): ocultar. |
| `actualizar_perfil(datos)` | — | **Fuera de la Entrega 1**: ocultar. |
| `likes`, `comentarios` | — | No existen: ocultar los contadores. |

**Para la demo** conviene un panel con los tres servidores y un interruptor de conexión por servidor (`PUT /api/servidores/{dominio}/conexion`), mostrando sus `pendientes`. Así se ve cómo converge el sistema tras una desconexión.
