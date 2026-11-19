# Comparación arquitectónica

> **Borrador (Entrega 1).** La versión final se completa en la entrega final, con la versión HTTP implementada y las mediciones de `mediciones.md`. Antes de cerrarla hay que verificar contra fuentes primarias los datos sobre Twitter/X y Mastodon (ver sección 5).

Se compara Blue Jay con tres referencias:

- **Twitter/X:** comparación funcional histórica de un sistema **centralizado**. Solo se usa como referencia; Blue Jay no reutiliza su marca ni su terminología.
- **ActivityPub:** estándar abierto del W3C para federación entre servidores sociales. Es un **protocolo**, no una implementación.
- **Mastodon:** implementación desplegada de micropublicaciones federadas sobre ActivityPub.

---

## 1. Clasificación general (Conf. 1)

| | Twitter/X (histórico) | ActivityPub | Mastodon | Blue Jay (Ray, Entrega 1) | Blue Jay (HTTP, final) |
|---|---|---|---|---|---|
| **Organización** | Distribuido pero **centralizado en control**: un solo dueño | Define cómo se federan servidores **descentralizados** | **Descentralizado**: miles de instancias independientes | **Descentralizado** (lógicamente): un actor por servidor | **Descentralizado**: un proceso y una base de datos por servidor |
| **Eje de escala dominante** | Tamaño (usuarios, peticiones) | Administrativo | Administrativo | Administrativo (simulado) | Administrativo |
| **¿Dónde está la verdad?** | En el sistema central | En el servidor de cada actor | En la instancia de cada usuario | En el servidor de cada usuario | En el servidor de cada usuario |
| **Elección ante partición (CAP)** | Puede priorizar consistencia dentro de su infraestructura | No lo fija | Disponibilidad: cada instancia sigue funcionando | Disponibilidad (D4, D14) | Disponibilidad |

---

## 2. Las seis dimensiones (Conf. 2)

| Dimensión | Twitter/X (histórico) | ActivityPub | Mastodon | Blue Jay (Ray) | Blue Jay (HTTP) |
|---|---|---|---|---|---|
| **1. Estado y datos** | Un único dueño de todos los datos, particionados internamente. Empezó con MySQL y Ruby on Rails (Conf. 1) | Cada actor tiene su servidor; los demás guardan copias | PostgreSQL por instancia; copias en caché de lo remoto | Memoria privada de cada actor (D3); copias de lo remoto | Base de datos propia por servidor |
| **2. Acoplamiento** | Interno; el usuario no ve la propagación | Entrega servidor a servidor por `POST` al inbox; el estándar no fija si es síncrona | Asíncrono: colas de trabajos con reintentos | Asíncrono: `EntregadorActor` (D4, D6) | Asíncrono: cola de trabajos |
| **3. Topología y escala** | Particionado y replicado dentro de una infraestructura propia | Federación entre servidores iguales | Federación de instancias | Partición por dominio; tres servidores en un clúster | Partición por dominio, servidores en máquinas distintas |
| **4. Descubrimiento** | Interno | Fuera del estándar (en la práctica, WebFinger) | WebFinger + documento del actor | Registro de nombres de Ray / GCS (D16) | WebFinger + DNS |
| **5. Fallos parciales** | Caídas visibles al saturarse (la *fail whale*, Conf. 1) | No lo especifica | Reintentos con espera creciente; una instancia caída no afecta a las demás | Modo offline, reintentos con *backoff*, *dead letter* (D6, D14) | Igual, con caídas reales de procesos y red |
| **6. Semántica y observabilidad** | Consistencia más fuerte dentro del sistema central | Actividades con ID; no define garantías de entrega | Consistencia eventual entre instancias | *At-least-once* + deduplicación = efecto *exactly-once* (D7); FIFO por origen; causal para republicaciones | Igual |

---

## 3. Aspectos funcionales

| Aspecto | Twitter/X (histórico) | ActivityPub | Mastodon | Blue Jay |
|---|---|---|---|---|
| **Propagación** | Interna al sistema | *Push* al inbox de los destinatarios | *Push* al inbox o al *shared inbox* | *Push* asíncrono, una copia por servidor destino (D4, D5) |
| **Líneas de tiempo** | Híbrido: *fan-out* al escribir para la mayoría y al leer para cuentas con muchísimos seguidores | No lo define: queda a cada implementación | *Fan-out* al escribir | *Fan-out* al escribir (D8); orden por hora del origen (D9) |
| **Visibilidad** | Pública o cuenta protegida | Direccionamiento con `to` / `cc` y la colección pública | Pública, no listada, solo seguidores, directa | Pública y solo seguidores (Entrega 1) |
| **Cuentas protegidas** | Sí | `Follow` / `Accept` / `Reject` | Cuentas bloqueadas con aprobación manual | `pending` → `accepted` (Entrega 1) |
| **Eliminación** | Efectiva dentro del sistema central | Actividad `Delete`; el objeto puede reemplazarse por un `Tombstone` | Propaga `Delete`; el borrado en otras instancias depende de ellas | `Delete` a quien la recibió o pidió, más *tombstone* (D13) |
| **Duplicados y orden** | Resueltos internamente | IDs únicos por actividad | Deduplicación por ID | Deduplicación + idempotencia (D7); FIFO por destino (D6); espera causal (D12) |
| **Autenticación entre servidores** | No aplica (un solo dueño) | Fuera del estándar | HTTP Signatures | Ninguna en la Entrega 1 (D15); HTTP Signatures en la final |
| **Moderación** | Central | Fuera del estándar | Por instancia, con bloqueo de dominios | Fuera del alcance de la Entrega 1 |

---

## 4. Qué toma Blue Jay de cada referencia y en qué difiere

**De ActivityPub** toma:
- el modelo de actores con inbox;
- los tipos de actividad (`Create`, `Follow`, `Accept`, `Announce`, `Undo`, `Delete`);
- las URIs como identificadores.

Así la versión HTTP puede acercarse al estándar sin cambiar el núcleo (D2).

**De Mastodon** toma:
- la entrega asíncrona con reintentos;
- el *shared inbox*;
- el *fan-out* al escribir;
- las cuentas con aprobación manual.

**Difiere de Mastodon** en tres puntos:
- La cola es **FIFO por destino y acotada**, con *dead letter* explícita (D6), siguiendo Conf. 3 y Conf. 4.
- **Retiene una republicación hasta tener su original** (D12), para garantizar consistencia causal (Conf. 6).
- Define por escrito qué pasa en cada caso de visibilidad (`visibilidad.md`).

**Frente a Twitter/X**, Blue Jay renuncia a que un solo dueño garantice consistencia fuerte y borrado efectivo. A cambio obtiene independencia administrativa y disponibilidad ante particiones. Es el compromiso CAP de Conf. 1: la consistencia fuerte cuesta disponibilidad.

---

## 5. Pendiente para la versión final

- [ ] Verificar contra fuentes primarias la arquitectura histórica de Twitter/X: modelo híbrido de líneas de tiempo, almacenamiento.
- [ ] Verificar contra la documentación de Mastodon: política de reintentos, *shared inbox*, almacenamiento de líneas de tiempo.
- [ ] Citar las secciones concretas de la especificación de ActivityPub (W3C).
- [ ] Completar la columna "Blue Jay (HTTP)" con lo implementado.
- [ ] Respaldar la comparación de compromisos con los números de `mediciones.md`.
