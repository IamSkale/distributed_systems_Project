# Cambios remotos, eliminaciones y desconexiones

Qué pasa en Blue Jay cuando algo sale mal entre servidores: qué hace el sistema, qué ve el usuario y cómo converge. Cubre la **Entrega 1 (versión con Ray)**. Las decisiones citadas (D1–D17) están en `decisiones.md`; las conferencias, en la tabla de referencias de ese documento.

Cada escenario tiene una prueba con actores de Ray en `tests/federacion/` y, cuando la lógica es del núcleo, otra sin Ray en `tests/dominio/test_federacion_manual.py`.

---

## 0. Modelo de fallos

**Qué fallos se consideran.**
- **Servidor no disponible.** Se simula con `set_online(False)` (D14): los métodos federados (`inbox`, `obtener_objeto`, `obtener_actor`) fallan con `ServidorNoDisponible` y el entregador propio se pausa. Las operaciones locales siguen funcionando. Para quien llama, un servidor caído, lento o particionado se ve igual (Conf. 1 y 3): las tres situaciones llegan como un error o un *timeout*.
- **Actor muerto o reiniciado.** `RayActorError`. El directorio descarta la referencia en caché y la vuelve a resolver en el próximo intento (*stale reference*, Conf. 4; D16).
- **Destino desconocido.** `ServidorDesconocido`: no hay un actor registrado con ese dominio. Se trata como un error de transporte, porque el servidor puede aparecer más tarde.
- **Mensajes duplicados o desordenados.** La entrega es *at-least-once* (Conf. 4), así que puede haber duplicados. En Ray el orden por destino está garantizado (D6), pero el modelo no depende de eso: el núcleo tolera el desorden, como hará falta en la versión HTTP.
- **Mensajes defectuosos.** Una actividad que el receptor rechaza (`ActividadInvalida`) o que lo hace fallar de forma inesperada.

**Qué no se considera.** Los servidores maliciosos (no hay firmas, D15) y la pérdida de estado por un *crash-stop* real: el estado vive en memoria (D3), así que matar un actor borra sus datos. Ver la sección 10.

**Clasificación de errores en el entregador** (`bluejay/ray_app/entregador.py`):

| Error | Ejemplo | Qué hace | Por qué |
|---|---|---|---|
| De transporte | `ServidorNoDisponible`, `RayActorError`, `ServidorDesconocido`, *timeout* | Reintenta con *backoff*; tras el máximo de intentos, *dead letter* | No es culpa de la actividad: puede funcionar más tarde (Conf. 4) |
| Rechazo del receptor | `ActividadInvalida` | *Dead letter* directa, sin reintentos | Reintentar no la arregla: es una *poison pill* (Conf. 4) |
| Inesperado | cualquier otra excepción del receptor | *Dead letter* directa ("error inesperado") | Igual que una *poison pill*: si no, la cola de ese destino quedaría trabada |

**Valores** (`ConfigRay`): 6 intentos con esperas de 1, 2, 4, 8 y 16 s (31 s en total antes de rendirse), *timeout* de 2 s por llamada y cola de 1000 actividades por destino. En producción las esperas serían de minutos a horas (D6). Las pruebas usan valores más cortos (`config_pruebas`, `config_paciente`).

**Resumen de escenarios:**

| # | Escenario | Mecanismo | ¿Converge? | Prueba con Ray |
|---|---|---|---|---|
| 1 | Servidor destino caído | Cola por destino + reintentos (D6, D14) | Sí, al reconectar | `test_destino_caido.py`, `test_offline_reintento.py` |
| 2 | Reintentos agotados | *Dead letter* (D6) | **No** para lo perdido | `test_reintentos_agotados.py` |
| 3 | `Delete` antes que `Create` | *Tombstone* (D13) | Sí | `test_delete_antes_que_create.py` |
| 4 | Actividad duplicada | Deduplicación + idempotencia (D7) | Sí | `test_actividad_duplicada.py` |
| 5 | `Announce` de algo desconocido, origen caído | Pendientes por dependencia + *pull* (D12) | Sí, al volver el origen | `test_announce_origen_caido.py`, `test_republicar_dependencia.py` |
| 6 | Solicitud pendiente y "solo seguidores" | Destinos y filtro por seguidor aceptado | — (no hay nada que converger) | `test_pendiente_solo_seguidores.py` |
| 7 | Dejar de seguir con entregas en vuelo | Decisión local en el receptor (D11) | Sí | `test_dejar_de_seguir_en_vuelo.py`, `test_dejar_de_seguir.py` |
| 8 | Actividad inválida (*poison pill*) | *Dead letter* sin reintentos (D6) | La cola sigue | `test_actividad_invalida.py`, `test_error_inesperado.py` |
| 9 | Cola llena | Cola acotada + *load shedding* (D6) | **No** para lo descartado | `test_cola_llena.py` |

---

## 1. Servidor destino caído

**Escenario.** Ana (alpha) y Caro (gamma) siguen a Beto (beta). Gamma se desconecta y Beto publica.

**Qué pasa.**
1. `publicar` responde de inmediato en beta: encola una entrega por servidor destino (D4, D5) y no espera a nadie.
2. La entrega hacia alpha sale enseguida. La de gamma falla con `ServidorNoDisponible`, que es un error de transporte. El entregador de beta suma un intento y espera antes de volver a probar (1, 2, 4… s).
3. Cada destino tiene su propia cola y su propio bucle (D6). Que gamma esté caído no demora la entrega a alpha. El bloqueo de cabeza de línea (Conf. 2) queda **acotado a gamma**, y no cuesta nada: los demás mensajes para gamma también fallarían.
4. Cuando gamma vuelve (`set_online(True)`), el próximo reintento entra y la cola hacia gamma se vacía **en orden**.

**Qué ve el usuario.**
- Beto publica sin notar nada.
- Ana ve la publicación al instante.
- Caro no la ve mientras gamma está desconectado. Su servidor sigue funcionando para lo local: puede leer su inicio y publicar, y lo que publica queda en la cola pausada de gamma (D14).
- Al reconectarse, la publicación aparece en el inicio de Caro, en su lugar cronológico según la hora de origen (D9), no arriba de todo como si fuera nueva.

**Cómo converge.** Sin intervención, siempre que gamma vuelva antes de agotar los reintentos (31 s con la configuración de la demo). Es la reconciliación de Conf. 5: durante la partición cada lado funciona con lo que tiene, y al reconectarse se intercambian las novedades pendientes. La cola de salida hace de *buffer*, como un broker (Conf. 2 y 4). Es una elección **AP** (CAP, Conf. 1): Blue Jay sigue disponible y acepta que gamma esté desactualizado un rato.

**Prueba.** `test_destino_caido.py` comprueba que alpha la recibe mientras gamma está caído, que la entrega hacia gamma se reintenta y que, al reconectar, Caro la ve sin *dead letters*. `test_offline_reintento.py` hace lo mismo con un `Follow`.

---

## 2. Reintentos agotados (*dead letter*)

**Escenario.** Gamma está desconectado más tiempo que el total de los reintentos.

**Qué pasa.** Tras el sexto intento fallido, el entregador de beta saca la actividad de la cola y la guarda en *dead letter* con el motivo `máximo de intentos agotado (...)`. La cola hacia gamma queda libre: lo próximo que Beto publique se entrega normalmente cuando gamma vuelva.

Rendirse es una decisión deliberada. Reintentar para siempre haría crecer la memoria sin límite si gamma no vuelve nunca (cola ilimitada = anti-patrón, Conf. 3). Además, un *timeout* no dice si el destino cayó o solo está lento (Conf. 4): en algún momento hay que dejar de esperar.

**Qué ve el usuario.**
- Caro **nunca** ve esa publicación, ni siquiera cuando gamma se reconecta. Sí ve las siguientes.
- La publicación sigue existiendo en beta: el perfil de Beto la muestra a quien lo mire desde beta.
- Beto no recibe ningún aviso. La *dead letter* solo se observa con `transporte()` (administración y pruebas).

**Qué se pierde según el tipo de actividad.** Es la parte más delicada, porque no todas las pérdidas son iguales:

| Actividad perdida | Efecto | ¿Grave? |
|---|---|---|
| `Create` | La publicación falta en el destino | Leve: falta contenido, pero lo que se muestra es correcto |
| `Announce` | La republicación falta en el destino | Leve |
| `Follow` | El seguidor queda en `pending` para siempre en su servidor | Hay que volver a intentar a mano (dejar de seguir y seguir de nuevo) |
| `Accept` | Igual: el seguidor queda en `pending`, pero el seguido ya lo cuenta como aceptado y le entrega | Divergencia entre los dos servidores |
| `Undo(Follow)` | El seguido sigue entregando al servidor del exseguidor | Leve: el receptor lo descarta (sección 7). Es tráfico de más |
| `Delete` | **La copia sigue visible en el destino** | Grave para la privacidad: lo eliminado no desaparece |

**Cómo se resolvería** (fuera del alcance de la Entrega 1). Con *push-pull* (Conf. 5): al reconectarse, gamma le pide a beta lo que cambió desde la última entrega confirmada (publicaciones nuevas y eliminaciones). Eso cubre todas las filas de la tabla, incluido el `Delete`. Una alternativa más simple sería reprocesar las *dead letters* de tipo transporte cuando el destino vuelve a responder.

**Prueba.** `test_reintentos_agotados.py` comprueba que la entrega termina en *dead letter* con el motivo correcto, que la publicación sigue en el perfil de Beto, que no llega a gamma al reconectar y que la siguiente sí llega.

---

## 3. `Delete` antes que `Create`

**Escenario.** Alpha recibe el `Delete` de una publicación de Beto antes que su `Create`.

**¿Cuándo puede pasar?** Entre dos servidores no pasa en el camino normal: la cola FIFO por destino (D6) entrega las actividades de beta a alpha en el orden en que se generaron (FIFO por emisor, Conf. 6). Pero el núcleo no puede depender de eso:
- **El original pedido por *pull*** (D12). Gamma pide a beta un original con `obtener_objeto`. Beta lo sirve y anota a gamma como destino del `Delete`. Si Beto lo elimina enseguida, el `Delete` puede llegar al `inbox` de gamma mientras gamma todavía espera la respuesta: el actor es asíncrono y atiende otras llamadas durante un `await` (D17).
- **La versión HTTP.** Dos peticiones concurrentes no tienen orden garantizado (Conf. 4).

**Qué pasa.** El `Delete` de una publicación desconocida no falla: borra lo que haya (nada) y deja un ***tombstone*** con la URI (D13). Cuando llega el `Create`, el *tombstone* hace que se ignore. Funciona como el número de encarnación de SWIM (Conf. 5): la noticia más nueva (la eliminación) gana sobre una más vieja que llega tarde. En el caso del *pull*, `recibir_objeto` revisa los *tombstones* al volver del `await` (D17), así que el original tampoco entra.

**Qué ve el usuario.** Ana no ve la publicación en ningún momento, ni siquiera por un instante.

**Cómo converge.** De inmediato. El resultado es el mismo que con el orden correcto: los dos servidores coinciden en que la publicación no existe.

**Costo.** Los *tombstones* no se borran nunca en esta entrega. Crecen con el número de eliminaciones. En la entrega final tendrían una ventana de tiempo mayor que el reintento más largo posible.

**Prueba.** `test_delete_antes_que_create.py` entrega a mano, directo al `inbox` de alpha, el `Delete` y después el `Create` (más un reintento del `Create`). Hay que hacerlo a mano porque el entregador nunca las invierte.

---

## 4. Actividad duplicada

**Escenario.** Alpha recibe dos veces el mismo `Create`.

**¿Cuándo puede pasar?** La entrega es *at-least-once* (D6): si el *timeout* del entregador vence **después** de que alpha procesó la actividad, el entregador no puede saber que llegó (se perdió el "ACK", Conf. 4) y la reintenta. También pasa si el mismo contenido llega por dos caminos.

**Qué pasa.** Hay dos defensas (D7):
1. **Deduplicación por ID de actividad.** Alpha guarda los IDs procesados. Un ID repetido se responde como éxito, sin volver a ejecutarse. Hay que responder éxito: si se respondiera error, el emisor reintentaría para siempre.
2. **Handlers idempotentes.** Un `Create` con otro ID pero de una publicación que ya existe no crea otra copia. Esto cubre el caso en que el registro de IDs no alcanza (por ejemplo, si se perdiera al reiniciar el actor, D3).

*Exactly-once* no es una propiedad de la red: se construye con *at-least-once* más idempotencia y deduplicación en el receptor (Conf. 4).

**Qué ve el usuario.** La publicación aparece una sola vez.

**Prueba.** `test_actividad_duplicada.py` entrega el mismo `Create` dos veces (el contador de actividades procesadas no cambia la segunda vez) y una tercera con otro ID para la misma publicación.

---

## 5. `Announce` de una publicación desconocida

**Escenario.** Caro (gamma) sigue a Ana (alpha), pero no a Beto (beta). Ana republica una publicación de Beto. Gamma nunca recibió el original, y además beta está desconectado.

**Qué pasa** (D12).
1. Gamma **acepta** el `Announce`: le confirma la entrega a alpha y lo guarda en **pendientes por dependencia**. Rechazarlo para que alpha reintente trabaría toda la cola de alpha hacia gamma por culpa de un tercero (D6).
2. Gamma le pide el original a beta con `obtener_objeto` (*pull*, Conf. 5). Beta no responde, así que gamma reintenta con *backoff*, cada original por separado, sin frenar a los demás.
3. Mientras tanto, lo demás que alpha le entrega a gamma sigue pasando: la dependencia pendiente no bloquea la cola.
4. Cuando beta vuelve, gamma obtiene el original, lo guarda y recién entonces la republicación entra al inicio de Caro.

**Qué ve el usuario.**
- Mientras falta el original, Caro **no ve la republicación**, pero sí lo demás que publica Ana.
- Cuando llega el original, la republicación aparece con la etiqueta "republicado por Ana".
- Nunca ve una republicación "vacía" o de algo que no puede leer. Es la garantía causal "el original antes que la republicación" (Conf. 6): el protocolo la cumple con **espera y almacenamiento temporal**, no con marcas de tiempo.

**Casos borde.**
- **Ana deshace la republicación mientras gamma espera:** el `Undo` saca la dependencia de pendientes. Si el original llega después, nadie lo espera y se descarta (verificar de nuevo al volver del `await`, D17).
- **Beto elimina el original mientras gamma espera:** beta responde con un `Tombstone` y gamma abandona la dependencia.
- **El original es "solo seguidores" o no existe:** beta responde `None` y gamma abandona la dependencia.
- **Beta no vuelve antes de agotar los reintentos:** gamma abandona la dependencia y la republicación no se muestra nunca. Es la misma pérdida de la sección 2, pero nunca muestra algo incorrecto.

**Prueba.** `test_announce_origen_caido.py` comprueba que gamma queda con una dependencia pendiente, que lo que Ana publica mientras tanto llega igual, y que al volver beta la republicación aparece y la dependencia se libera. `test_republicar_dependencia.py` cubre el caso con beta conectado. Los casos borde están en `test_federacion_manual.py`.

---

## 6. Solicitud de seguimiento pendiente y publicación "solo seguidores"

**Escenario.** Ana (alpha) pide seguir a Bea (beta), que tiene la cuenta protegida. Mientras la solicitud está pendiente, Bea publica una publicación "solo seguidores" y una pública.

**Qué pasa.** Un seguimiento `pending` no cuenta como seguidor para nada (`visibilidad.md`, 1). La privacidad se aplica dos veces:
- **Al enviar:** los destinos de una publicación de Bea son los servidores con al menos un seguidor **aceptado** de Bea (D5). Alpha no tiene ninguno, así que no se le envía nada, ni siquiera la pública.
- **Al leer:** aunque alpha tuviera la publicación (porque otro usuario de alpha sí sigue a Bea), el inicio de Ana solo incluye publicaciones de cuentas que ella sigue con seguimiento aceptado, y el perfil se filtra por observador.

**Qué ve el usuario.**
- Ana no ve nada de Bea, ni en su inicio ni en el perfil de Bea consultado desde alpha.
- Cuando Bea acepta, Ana empieza a recibir **solo lo publicado después**. No se rellena el historial (D11, `visibilidad.md`).

**Prueba.** `test_pendiente_solo_seguidores.py`. Para comprobar que "no llegó nada" sin esperar un tiempo arbitrario se usa el orden FIFO por destino como barrera: después de aceptar, Bea publica otra cosa. Cuando esa llega a alpha, cualquier entrega anterior ya habría llegado, y el inicio de Ana contiene solo esa última.

---

## 7. Dejar de seguir con entregas en vuelo

**Escenario.** Alpha está desconectado cuando Beto publica, así que el `Create` queda reintentándose en la cola de beta. Mientras tanto Ana deja de seguir a Beto: es una operación local y funciona aunque alpha esté desconectado (D14). Su `Undo(Follow)` queda en la cola pausada de alpha. Al reconectarse, las dos actividades se cruzan.

**Qué pasa.** Hay dos órdenes posibles:
- El `Create` llega a alpha antes de que el `Undo` llegue a beta.
- El `Undo` llega a beta antes, y beta ya no tiene a quién enviar en alpha (aunque el `Create` ya estaba encolado).

En los dos casos alpha decide con **su estado local**: el efecto de dejar de seguir fue inmediato en alpha (D11), así que una publicación de Beto que llega después no entra al inicio de Ana. La decisión no depende de qué servidor se entere primero. Esto es "capturar → liberar → llamar → **verificar**" (Conf. 3; D17): el estado en el que se tomó la decisión de enviar ya no vale cuando el mensaje llega, y el receptor vuelve a verificar.

Si la publicación es pública, alpha guarda una copia que nadie ve. Si es "solo seguidores", no la guarda (`visibilidad.md`).

**Qué ve el usuario.** Al dejar de seguir, las publicaciones de Beto desaparecen del inicio de Ana de inmediato, y no reaparecen con las entregas atrasadas.

**Cómo converge.** Cuando el `Undo(Follow)` llega a beta, Beto deja de tener a Ana como seguidora y beta deja de enviarle. Si el `Undo` se perdiera (sección 2), beta seguiría enviando a alpha y alpha seguiría descartando: es tráfico de más, pero no un error visible.

**Prueba.** `test_dejar_de_seguir_en_vuelo.py` arma el escenario con entregas que de verdad están en vuelo (alpha desconectado). `test_dejar_de_seguir.py` cubre el caso normal.

---

## 8. Actividad inválida (*poison pill*)

**Escenario.** Alpha envía un `Follow` a `@ghost@beta.local`, un usuario que no existe. Detrás, en la misma cola, va un `Follow` válido a Beto.

**Qué pasa.** Beta lo rechaza con `ActividadInvalida`. El entregador de alpha lo manda **directo** a *dead letter*, sin reintentos, y sigue con el siguiente. Si se reintentara, fallaría siempre y trabaría la cola de alpha hacia beta: un mensaje defectuoso con reintento infinito detiene los mensajes válidos (*poison pill*, Conf. 4). La *dead letter* es la cola de cuarentena que rompe ese ciclo y deja el mensaje disponible para diagnosticarlo (Conf. 4).

Lo mismo pasa con un error inesperado del receptor (un fallo interno al procesar): se trata como una *poison pill*, porque reintentar no lo arregla. Si el entregador no lo capturara, el bucle de ese destino moriría con la actividad en la cabeza y la cola quedaría trabada para siempre.

Otros motivos de rechazo: una actividad cuyo `actor` no pertenece al dominio que la entrega (D15), un `Delete` de una publicación ajena, un `Announce` de una publicación "solo seguidores" o campos obligatorios faltantes.

**Qué ve el usuario.** El seguimiento a `ghost` queda en `pending` en alpha (no llega ningún `Accept`). El seguimiento a Beto funciona normalmente.

**Prueba.** `test_actividad_invalida.py` comprueba la *dead letter* sin reintentos y que el `Follow` válido que iba detrás llega. `test_error_inesperado.py` hace lo mismo con un receptor que falla de forma inesperada.

---

## 9. Cola llena

**Escenario.** Un destino lleva mucho tiempo sin responder y hay más de 1000 actividades pendientes hacia él.

**Qué pasa.** La cola por destino está **acotada** (D6). Cuando se llena, las actividades nuevas para ese destino van a *dead letter* con el motivo "cola llena". Se descartan las nuevas, no las viejas, para no romper el orden de lo que ya está en la cola. El usuario que publica no se bloquea: bloquearlo lo haría depender de un servidor remoto (acoplamiento síncrono, D4).

Es *load shedding*. Una cola sin límite es un anti-patrón: se acumula en memoria hasta que el sistema muere. La alternativa es rechazar de forma explícita (*backpressure*) o descartar (Conf. 3 y 4).

**Qué ve el usuario.** Lo mismo que en la sección 2: lo descartado nunca llega a ese destino. Los demás destinos no se ven afectados.

**Memoria.** Lo pendiente está acotado: como mucho 1000 actividades por destino.

**Prueba.** `test_cola_llena.py` (con una cola de 5): con la cola pausada, de 7 publicaciones quedan 5 pendientes y 2 en *dead letter* con "cola llena".

---

## 10. Limitaciones conocidas de esta entrega

- **Lo que va a *dead letter* no se recupera.** No hay *pull* de reconciliación ni reproceso (secciones 2 y 9). La pérdida de un `Delete` deja contenido eliminado visible en otro servidor.
- **Las *dead letters* no tienen límite.** La cola de cuarentena crece sin tope; en la entrega final tendría un tamaño máximo o se volcaría a disco.
- **El estado vive en memoria** (D3). Un *crash-stop* real (Conf. 3) se lleva el estado del servidor, sus colas pendientes y su registro de deduplicación. Por eso las desconexiones se simulan con el modo *offline* (D14). La tarea opcional F.2 (SQLite + `ray.kill` + reinicio) cubriría este caso.
- **Los *tombstones* y el registro de IDs procesados crecen sin límite** (secciones 3 y 4).
- **Un único dominio de fallo físico.** En un solo nodo, los tres servidores comparten la máquina (D1). La independencia de los fallos es lógica, no física, hasta la tarea opcional F.3.
- **El autor no se entera** de que una entrega se perdió.
