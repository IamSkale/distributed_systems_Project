# Semántica de visibilidad y líneas de tiempo

Qué ve cada usuario, dónde, en qué orden y con qué garantías. Cubre la **Entrega 1 (versión con Ray)**. Las decisiones citadas (D1–D17) están en `decisiones.md`.

---

## 1. Conceptos

- **Seguidor aceptado:** quien tiene un seguimiento en estado `accepted` hacia el autor. Un seguimiento `pending` (solicitud a una cuenta protegida sin responder) **no cuenta como seguidor** para ningún efecto.
- **Cuenta protegida:** solo cambia **cómo se aceptan los seguidores** (con aprobación manual). No cambia la visibilidad de cada publicación, que la elige el autor al publicar.
- **Observador:** el usuario que mira una línea de tiempo. En la Entrega 1 no hay inicio de sesión. Las operaciones de lectura reciben `visto_por` (un usuario local) o `None` (anónimo).

---

## 2. Niveles de visibilidad

En la Entrega 1 hay dos niveles. "No listada" y "directa" quedan para la entrega final.

| Visibilidad | ¿En el perfil del autor? | ¿En el inicio de los seguidores? | ¿Se puede republicar? | ¿A qué servidores se envía? |
|---|---|---|---|---|
| **Pública** (`public`) | Sí, para cualquiera, incluido un anónimo | Sí, para seguidores aceptados | Sí, por cualquiera que la vea | A cada servidor con al menos un seguidor aceptado del autor (una copia por servidor, D5) |
| **Solo seguidores** (`followers`) | Solo para el autor y sus seguidores aceptados | Sí, para seguidores aceptados | **No**, ni siquiera el autor | **Solo** a servidores con al menos un seguidor aceptado. Nunca a otros |

**Regla de privacidad:** una publicación "solo seguidores" nunca sale hacia un servidor donde el autor no tenga seguidores aceptados. Se aplica **al enviar** (cálculo de destinos) y **al leer** (filtro por observador). En el receptor solo la ven los seguidores aceptados, no los demás usuarios de ese servidor.

---

## 3. Línea de tiempo de inicio

Es la línea de un usuario local. Contiene:

1. Sus propias publicaciones (de cualquier visibilidad) y sus propias republicaciones.
2. Las publicaciones de quienes sigue con seguimiento **aceptado**, públicas y "solo seguidores".
3. Las republicaciones hechas por quienes sigue. Solo existen republicaciones de publicaciones públicas.

No contiene:
- Publicaciones de cuentas a las que el usuario solo tiene una **solicitud pendiente**.
- Publicaciones **eliminadas** (D13).
- Republicaciones cuyo original **todavía no llegó** a este servidor. Quedan en espera hasta tenerlo (D12).

---

## 4. Línea de tiempo de perfil

Muestra las publicaciones y republicaciones de un usuario, filtradas según quién mira:

| Observador | Ve las públicas | Ve las "solo seguidores" |
|---|---|---|
| El propio autor | Sí | Sí |
| Seguidor aceptado | Sí | Sí |
| Seguidor con solicitud pendiente | Sí | No |
| Usuario que no lo sigue | Sí | No |
| Anónimo (`visto_por=None`) | Sí | No |

**Perfil de un usuario remoto:** cada servidor solo muestra **lo que conoce**, es decir, las copias que recibió o pidió. No consulta el historial completo al servidor de origen. El perfil remoto puede estar incompleto: es una vista local y parcial, como la de cada participante en Conf. 5.

---

## 5. Orden

- Ambas líneas se ordenan de la más reciente a la más antigua según la **hora de publicación en el servidor de origen** (`published`), con la URI como desempate (D9).
- Una republicación se ordena por la hora en que se **republicó**, no por la del original.
- Es un **orden de presentación**. La hora de pared no prueba qué ocurrió antes (Conf. 6). Las dependencias se garantizan con otros mecanismos (sección 7).
- Una publicación que llega tarde (por ejemplo, tras una desconexión) aparece en su lugar cronológico, no arriba de todo.

---

## 6. Casos particulares

| Situación | Comportamiento |
|---|---|
| **Empiezo a seguir a alguien** | Solo recibo sus publicaciones **nuevas**, desde que el seguimiento queda aceptado. No se trae el historial anterior. |
| **Mi solicitud a una cuenta protegida está pendiente** | No recibo nada. Si después me acepta, solo recibo lo nuevo. |
| **Me rechazan la solicitud** | El seguimiento se borra. Puedo volver a pedirlo. |
| **Dejo de seguir** | Se quitan de mi inicio sus publicaciones y republicaciones. Lo que llegue después (entregas en vuelo) se descarta (D11). |
| **Dos personas que sigo republican lo mismo** | Aparece **una vez**, con la etiqueta de quien republicó primero (D10). |
| **Republico algo dos veces** | La segunda vez no tiene efecto (idempotente). |
| **Intento republicar algo "solo seguidores"** | Se rechaza, incluso si soy el autor. |
| **El autor elimina una publicación** | Desaparece del perfil y de todas las líneas de inicio, en su servidor y en los que la recibieron o pidieron. También desaparecen sus republicaciones (D13). En los otros servidores desaparece cuando llega el `Delete`, no al instante. |
| **Llega una republicación de algo que no tengo** | Se guarda en espera, se pide el original al origen y solo se muestra cuando el original llega (D12). |
| **El servidor del autor está desconectado** | Sigo viendo las copias que ya tenía. Sus publicaciones nuevas me llegan cuando vuelva (D14). |
| **Mi propio servidor está desconectado** | Puedo publicar y ver mi inicio local. Mis publicaciones salen cuando el servidor vuelva (D14). |

---

## 7. Garantías de consistencia

El sistema es de **consistencia eventual** entre servidores (D4). Concretamente:

| Garantía | Qué asegura | Mecanismo |
|---|---|---|
| **Leer lo propio** (*read-your-writes*) local | El autor ve su publicación en su inicio y perfil inmediatamente. | Se inserta localmente antes de encolar las entregas. |
| **FIFO por origen** | Las actividades de un servidor llegan a cada destino en el orden en que se emitieron. Un `Delete` nunca adelanta a su `Create`. | Cola FIFO por destino (D6), orden FIFO de Conf. 6. |
| **Causalidad de republicaciones** | Una republicación nunca se ve antes que su original. | Espera de dependencias (D12), consistencia causal de Conf. 6. |
| **Efecto exactamente una vez** | Una actividad reintentada no duplica nada. | *At-least-once* + deduplicación + idempotencia (D7), Conf. 4. |
| **Convergencia** | Tras una desconexión, el servidor que vuelve recibe lo que se perdió, salvo lo que pasó a *dead letter*. | Reintentos con *backoff* (D6, D14). |

**Inconsistencias que el usuario puede observar** (y por qué son aceptables):

- **Retardo de propagación:** una publicación aparece en otros servidores después que en el de origen. Es el costo de no bloquear al autor (D4).
- **Eliminaciones no instantáneas:** una publicación borrada sigue visible en otro servidor hasta que llega el `Delete`.
- **Orden distinto entre servidores** para publicaciones independientes con horas muy cercanas. La consistencia causal permite que eventos concurrentes aparezcan en posiciones distintas (Conf. 6).
- **Perfiles remotos incompletos:** cada servidor muestra solo lo que conoce (sección 4).
- **Pérdida tras reintentos agotados:** si un destino estuvo caído más tiempo que todos los reintentos, esas actividades pasan a *dead letter* y no llegan. La reconciliación por *pull* queda como trabajo futuro.

---

## 8. Límite de la privacidad

Una vez que una publicación "solo seguidores" llega a otro servidor, que la siga ocultando depende de que **ese servidor se comporte correctamente**. Ningún mecanismo de esta entrega impide que un servidor malicioso la muestre o no la borre (D13; falacia 8 de Conf. 1: no todos los nodos son iguales ni confiables). Mastodon tiene exactamente el mismo límite.
