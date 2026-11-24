# Decisiones de diseño

Registro de las decisiones de Blue Jay en formato ADR (*Architecture Decision Record*): contexto, decisión, alternativas descartadas y consecuencias. Este documento cubre la **Entrega 1 (versión con Ray)**.

Cada decisión se justifica con los conceptos de las conferencias del curso:

| Ref. | Conferencia |
|---|---|
| Conf. 1 | Introducción: falacias, CAP, objetivos de diseño, Ray como andamiaje |
| Conf. 2 | Arquitecturas y middleware: seis dimensiones, estilos, Ray |
| Conf. 3 | El nodo y sus fronteras: concurrencia, vivacidad, colas acotadas, dominio de fallo |
| Conf. 4 | Comunicación: paradigmas, semánticas de entrega, idempotencia, mensajería |
| Conf. 5 | Comunicación II: diseminación, gossip, membresía |
| Conf. 6 | Tiempo, eventos y causalidad: relojes físicos y lógicos, órdenes de entrega |

**Estado de todas las decisiones:** aceptadas para la Entrega 1. Las que cambien en la entrega final se marcarán como "reemplazada por DX".

---

## D1. Un actor de Ray por servidor federado

**Contexto.** El enunciado pide servidores *administrados de forma independiente*, es decir, escalabilidad administrativa: sin autoridad única ni configuración global (Conf. 1). La Entrega 1 debe construirse con Ray, que ofrece dos unidades de ejecución: *tasks* sin estado y *actors* con estado aislado en memoria propia (Conf. 2). Cada servidor tiene estado (usuarios, publicaciones, seguimientos) que debe pertenecerle solo a él.

**Decisión.** Cada servidor (`alpha.local`, `beta.local`, `gamma.local`) es un **actor de Ray con nombre**, `ServidorActor`, con su estado privado. Los servidores no comparten memoria: solo intercambian mensajes (actividades).

**Alternativas.**
- *Tasks + almacén externo* (Redis): es el patrón "microservicio con estado" (Conf. 4). Agrega un componente más y una dependencia de su disponibilidad (Conf. 2, enfoque "servicio").
- *Un único actor para todos los servidores:* sería un sistema centralizado y rompería la independencia que pide el enunciado.
- *Procesos separados comunicados por HTTP:* es la entrega final; para la Entrega 1 se pide Ray.

**Consecuencias.**
- Es una arquitectura **shared-nothing**: el estado tiene un propietario y los demás le envían comandos. Es "exclusión por diseño" y no "por contención" (Conf. 3), así que no hacen falta *locks*.
- Ray serializa las llamadas a un actor, lo que evita *data races* dentro de un servidor (Conf. 2). Las carreras lógicas siguen siendo posibles (ver D17).
- Se respeta el anti-patrón "Actors para todo" (Conf. 2): solo son actores los componentes que mantienen estado (servidor y entregador).
- Ray funciona como **middleware** (Conf. 1 y 2): resuelve descubrimiento, *scheduling* y transporte. Lo usamos como "andamiaje temporal" (Conf. 1): primero se usa, después se reemplaza por HTTP.
- **Limitación:** si todos los actores corren en una sola máquina, comparten un **único dominio de fallo** (Conf. 3): si cae la máquina, caen los tres servidores. La independencia es lógica, no física. La tarea opcional F.3 (clúster con un nodo por servidor) la convierte en física.

---

## D2. Separar el dominio del transporte

**Contexto.** La arquitectura define los límites de fallo y los contratos antes del código, y cambiarla en etapas avanzadas cuesta reescrituras (Conf. 2). Sabemos de antemano que el transporte cambiará de Ray a HTTP. Además, un middleware que oculta toda la complejidad viola la "ley de las abstracciones permeables" (Conf. 2).

**Decisión.** Toda la lógica (publicar, seguir, visibilidad, líneas de tiempo, procesamiento de actividades) vive en un **núcleo de Python puro** (`bluejay/dominio/`) que no importa Ray. El núcleo no envía nada: **devuelve la lista de entregas** (`[(dominio_destino, actividad), ...]`) y el actor se encarga de transportarlas.

**Alternativas.** Escribir la lógica directamente en los actores. Es más rápido al principio, pero acopla el diseño a Ray y obliga a reescribir para la entrega final.

**Consecuencias.**
- El **contrato** entre servidores son las actividades (formato inspirado en ActivityPub), no los métodos de Ray. Esto favorece la **apertura** (Conf. 1): interfaces y formatos estándar.
- El núcleo se prueba sin levantar Ray (pruebas rápidas y deterministas).
- Los fallos de red no quedan ocultos: el núcleo los recibe como resultado de las entregas, no como excepciones invisibles.

---

## D3. Estado en memoria dentro de cada actor

**Contexto.** Ray no es una base de datos: los objetos viven en memoria y no sirven para persistencia a largo plazo (Conf. 2). Un proceso puede morir en cualquier punto sin código de limpieza (*crash-stop*, Conf. 3).

**Decisión.** En la Entrega 1 el estado de cada servidor vive en la memoria de su actor. La persistencia con SQLite por servidor queda como tarea opcional (F.2).

**Alternativas.** SQLite desde el principio: agrega trabajo que no es el foco de la entrega. Postgres por servidor: es el plan de la entrega final.

**Consecuencias.**
- Si un actor muere, pierde su estado. Por eso las desconexiones se simulan con un **modo offline** (D14) y no matando el actor.
- Si un actor se reinicia, las referencias que otros tenían a él quedan inválidas (*stale reference*, Conf. 4). El directorio debe volver a resolverlas (D16).
- El registro de actividades procesadas (D7) también se pierde con el actor; ver las consecuencias de D7.

---

## D4. Propagación por *push* asíncrono

**Contexto.** La comunicación puede ser síncrona o asíncrona, y transitoria o persistente (Conf. 4). La síncrona y transitoria es simple pero frágil: el retardo de un servicio se propaga **en cascada** a los demás (Conf. 2 y 4), y separar componentes por red manteniendo un acoplamiento síncrono es el anti-patrón del **monolito distribuido** (Conf. 2). En la diseminación existen tres modalidades: *push*, *pull* y *push-pull* (Conf. 5).

**Decisión.** Cuando un usuario publica, su servidor responde de inmediato y **encola** la actividad para cada servidor destino. El `EntregadorActor` la entrega después al inbox remoto (*push*). Es comunicación **asíncrona y persistente** mientras el actor vive: la cola de salida funciona como el *buffer* de un broker (Conf. 2).

**Alternativas.**
- *Push síncrono* (publicar espera a todos los destinos): si `gamma` está caído, publicar en `beta` falla o se bloquea. Es acoplamiento temporal y monolito distribuido.
- *Pull* (cada servidor consulta periódicamente a los demás): el retardo depende del periodo de consulta y hay que consultar aunque no haya novedades.
- *Gossip* entre servidores (Conf. 5): sirve cuando el grupo es grande, cambiante y cada nodo solo conoce una vista parcial. Aquí los destinatarios están **definidos por el grafo de seguimiento** y el emisor los conoce, así que el envío directo es más simple y no repite mensajes.
- *Push-pull* (push normal + pull para reconciliar tras una partición): queda como trabajo futuro.

**Consecuencias.**
- Publicar nunca depende de la disponibilidad de otros servidores.
- El sistema es de **consistencia eventual** entre servidores: una publicación tarda un tiempo en verse en los demás (retardo de propagación) y puede no verse mientras el destino esté desconectado.
- Se elige **disponibilidad** frente a consistencia (CAP, Conf. 1): ante una partición, cada lado sigue funcionando con lo que tiene.

---

## D5. Una entrega por servidor destino (*shared inbox*)

**Contexto.** Una forma de medir la carga es el **fan-out**: cuántas cosas toca una petición (Conf. 1). Enviar una copia a cada destinatario por separado no escala (Conf. 4, multicast), y conocer a todos los destinatarios tiene costo (Conf. 5).

**Decisión.** El servidor de origen envía **una sola copia por servidor destino**, sin importar cuántos seguidores tenga allí. El servidor receptor calcula a qué usuarios locales corresponde. Es la misma idea que IP multicast, donde el paquete se replica en las bifurcaciones (Conf. 4): el servidor destino es la bifurcación.

**Alternativas.** Una entrega por seguidor: con 100 seguidores en `alpha`, `beta` enviaría 100 copias idénticas.

**Consecuencias.**
- El receptor necesita saber cuáles de sus usuarios siguen al autor. Lo sabe porque fue él quien envió el `Follow` y recibió el `Accept`.
- Las publicaciones "solo seguidores" se envían solo a servidores con al menos un seguidor **aceptado** (ver `visibilidad.md`).

---

## D6. Cola de entrega FIFO por destino, acotada, con reintentos y *dead letter*

**Contexto.**
- Un *timeout* no dice si el mensaje se perdió o si el servidor cayó (Conf. 4).
- Para no perder mensajes hay que reintentar, es decir, entregar **al menos una vez** (*at-least-once*, Conf. 4).
- La red no garantiza el orden: "crear" y "eliminar" pueden llegar al revés. La solución es ordenar **por clave de partición**: los mensajes con la misma clave se procesan en secuencia (Conf. 4).
- Un mensaje defectuoso que falla siempre (*poison pill*) bloquea la cola si se reintenta para siempre. Se aparta tras N intentos en una *dead letter queue* (Conf. 4).
- Una cola sin límite es un anti-patrón: acumula memoria hasta que el sistema muere. Hay que aplicar **backpressure** o *load shedding* (Conf. 3 y 4).

**Decisión.**
- **Una cola FIFO por servidor destino.** El dominio destino es la clave de partición: solo se intenta el primer mensaje de cada cola. Así se garantiza **orden FIFO por emisor** (Conf. 6) para cada par origen → destino.
- **Reintentos con espera exponencial** (*backoff*): en pruebas y demo, 1, 2, 4, 8 y 16 s; en producción serían 1 min, 5 min, 30 min, 2 h y 12 h.
- **Se distinguen dos tipos de fallo:**
  - *Error de transporte* (destino offline, actor muerto, *timeout*): se reintenta.
  - *Rechazo del receptor* (actividad inválida): es una *poison pill* y va directo a *dead letter*, sin reintentos.
- **Tras 6 intentos** el mensaje pasa a *dead letter* y se registra.
- **Cola acotada** (1000 mensajes por destino, configurable). Si se llena, los mensajes nuevos para ese destino van a *dead letter* con el motivo "cola llena" (*load shedding*). No se bloquea al usuario que publica, porque eso lo haría depender de un servidor remoto (D4).

**Alternativas.**
- *Una sola cola global:* un destino caído bloquearía las entregas a todos los demás.
- *Sin orden por destino* (reintentar cada mensaje por separado): un `Delete` podría llegar antes que su `Create`.
- *Reintentar para siempre:* un destino que no vuelve nunca acumula memoria sin límite.

**Consecuencias.**
- Mientras un destino está caído, sus mensajes esperan en orden. Es un bloqueo de cabeza de línea (*head-of-line blocking*, Conf. 2) **acotado a ese destino**, y es aceptable porque los demás mensajes para ese destino también fallarían.
- Un *timeout* puede ocurrir después de que el receptor ya procesó el mensaje. El reintento lo duplica, y por eso existe D7.

---

## D7. Idempotencia y deduplicación por ID de actividad

**Contexto.** *Exactly-once* no es una propiedad de la red: se construye combinando *at-least-once* en el transporte con **idempotencia** y **deduplicación por ID** en el receptor (Conf. 4). Un identificador de actualización permite reconocer duplicados (Conf. 5).

**Decisión.**
- Toda actividad tiene un ID único (`https://<dominio>/activities/<uuid>`).
- El receptor guarda los IDs ya procesados y, si recibe uno repetido, **responde éxito sin volver a ejecutarlo**.
- Además, cada *handler* es idempotente por sí mismo: un `Create` de una URI que ya existe no crea otra copia, y un `Follow` repetido no crea otra relación.

**Alternativas.** Solo deduplicar por ID. Si el registro se pierde (actor reiniciado), el receptor ya no distingue un reintento de una actividad nueva (Conf. 4). La idempotencia natural de cada *handler* cubre ese caso.

**Consecuencias.**
- El **efecto** es *exactly-once* aunque la entrega sea *at-least-once*.
- El registro de IDs crece sin límite en la Entrega 1. En la entrega final se le pondrá una ventana de tiempo.

---

## D8. Líneas de tiempo con *fan-out* al escribir

**Contexto.** Una red social de micropublicaciones es el caso "muchos datos + mucha lectura" (Conf. 1, como un *feed*). La reingeniería distribuida del *timeline* fue la salida de Twitter a sus caídas (Conf. 1).

**Decisión.** Cuando una publicación llega al inbox de un servidor, este la **inserta en la línea de inicio de cada seguidor local**. Leer el inicio es solo leer esa lista ya armada.

**Alternativas.** *Fan-out* al leer: armar el inicio en cada lectura consultando las publicaciones de todos los seguidos. Escribir es barato, pero leer es caro, y la lectura es la operación más frecuente.

**Consecuencias.**
- Encaja con el *push* (D4): el trabajo se hace al recibir, una vez.
- El costo de escribir crece con el número de seguidores locales.
- Eliminar o dejar de seguir obliga a quitar elementos de esas listas (D11, D13).

---

## D9. Orden de las líneas de tiempo: hora de origen, sin pretender causalidad

**Contexto.**
- Los relojes de distintas máquinas tienen **desfase** y **deriva**. La hora de pared puede ajustarse o saltar, y comparar lecturas de máquinas distintas no prueba el orden real (Conf. 6).
- La relación "ocurrió antes" la establecen los mensajes, no las horas. Los relojes de Lamport respetan la causalidad (a → b implica L(a) < L(b)), pero un número menor no demuestra causalidad. Los relojes vectoriales detectan concurrencia, a costa de O(N) metadatos y una membresía conocida (Conf. 6).
- La consistencia causal exige que una respuesta no se vea antes que su antecedente. Los eventos independientes pueden aparecer en posiciones distintas en cada réplica (Conf. 6).

**Decisión.**
- Las líneas de tiempo se ordenan por la **hora de pared del servidor de origen** (`published`), con la URI como desempate. Es un **orden de presentación**, no causal.
- Las garantías causales que el sistema sí ofrece no dependen del ordenamiento, sino de mecanismos explícitos:
  - **FIFO por origen**, por la cola por destino (D6).
  - **Una republicación nunca se muestra antes que su original**, por la espera de dependencias (D12).

**Alternativas.**
- *Hora de recepción:* cada servidor mostraría un orden distinto, y una publicación reintentada durante horas aparecería arriba como si fuera nueva.
- *Orden total (Lamport, dominio)* (Conf. 6): respeta la causalidad, pero los contadores de servidores que no se comunican avanzan a ritmos distintos. Un servidor muy activo tendría números altos y sus publicaciones viejas quedarían arriba. El orden no correspondería a lo que el usuario entiende por cronológico.
- *Relojes vectoriales:* necesitan un componente por servidor y conocer a todos los servidores. En una federación abierta los servidores entran y salen, así que no es viable.

**Consecuencias.**
- Una publicación que llega tarde aparece en su lugar cronológico, posiblemente debajo de otras más nuevas.
- Dos servidores pueden ordenar distinto publicaciones independientes con horas muy cercanas. Es aceptable según la consistencia causal (Conf. 6).
- En la Entrega 1 todos los actores comparten el reloj de una máquina, así que el desfase es prácticamente cero. En la versión HTTP o en un clúster el desfase existe y este documento ya lo contempla.

---

## D10. Una republicación repetida se muestra una sola vez

**Contexto.** Si dos personas que sigo republican la misma publicación, con *fan-out* al escribir (D8) llegarían dos elementos iguales al inicio.

**Decisión.** Si la publicación original ya está en la línea de inicio, no se agrega otra vez. Se conserva la primera aparición.

**Alternativas.** Mostrar cada republicación: es más fiel a "quién republicó", pero repite contenido.

**Consecuencias.** La etiqueta "republicado por X" muestra a quien republicó primero según el orden de llegada.

---

## D11. Dejar de seguir quita del inicio las publicaciones de esa persona

**Contexto.** Hay que definir si el inicio muestra "lo que alguna vez recibí" o "lo de quienes sigo ahora".

**Decisión.** Al dejar de seguir, se quitan del inicio las publicaciones y republicaciones de esa persona. Las que lleguen después del `Undo(Follow)` (entregas que ya estaban en vuelo) se descartan.

**Alternativas.** Conservar lo recibido. Es más barato, pero el inicio mostraría contenido de alguien a quien ya no se sigue.

**Consecuencias.** Si se vuelve a seguir, solo llegan las publicaciones nuevas: no hay relleno del historial (ver `visibilidad.md`).

---

## D12. Republicación de algo desconocido: pedirlo al origen y esperar

**Contexto.**
- Una republicación depende de su original. Mostrarla antes viola la consistencia causal (Conf. 6).
- Para entregar respetando la causalidad, el protocolo aplica **esperas o almacenamiento temporal** (Conf. 6).
- Pedir lo que falta a quien lo tiene es *pull* (Conf. 5).

**Decisión.**
- Cuando llega un `Announce` de una publicación que el receptor no tiene, **acepta la actividad** (confirma la entrega) y la guarda en una lista de **pendientes por dependencia**.
- Después pide el original al servidor de origen con `obtener_objeto`. Si el origen no responde, reintenta con *backoff*.
- La republicación solo aparece en las líneas de tiempo cuando el original está disponible.

**Alternativas.**
- *Rechazar el `Announce` para que el emisor reintente:* bloquearía toda la cola del emisor hacia ese destino (D6) por culpa de un tercer servidor.
- *Incluir el original dentro del `Announce`:* el receptor no podría verificar que el contenido es auténtico, porque lo afirma un tercero.

**Consecuencias.**
- La garantía causal "original antes que republicación" se cumple en todos los servidores.
- El origen registra qué servidores le pidieron cada publicación, para enviarles después el `Delete` (D13).

---

## D13. Eliminación con `Delete` y *tombstone*

**Contexto.**
- Las actividades pueden llegar desordenadas o tarde (Conf. 4).
- Hace falta una regla para que una noticia vieja no reemplace a una más reciente. En SWIM se usa el número de **encarnación**: un rumor tardío con versión menor se descarta (Conf. 5).

**Decisión.**
- Al eliminar, el origen envía `Delete` a todos los servidores que **recibieron** la publicación (D5) o la **pidieron** (D12).
- El receptor borra su copia, la quita de las líneas de tiempo, elimina sus republicaciones locales y guarda un ***tombstone*** con la URI.
- Un `Create` que llega después de su `Delete` encuentra el *tombstone* y se ignora. El *tombstone* funciona como una versión "más nueva" que gana siempre.

**Alternativas.** Borrar sin dejar rastro. Un `Create` atrasado (por un reintento) "resucitaría" la publicación.

**Consecuencias.**
- Con D6 (FIFO por destino), el `Delete` del mismo origen nunca adelanta a su `Create`. El *tombstone* cubre los demás casos, como el original pedido por D12.
- **Límite de confianza:** una vez que el contenido llegó a otro servidor, que lo borre depende de que ese servidor se comporte bien. No se puede garantizar el borrado en un servidor malicioso (falacia 8, "la red es homogénea", Conf. 1).

---

## D14. Desconexiones simuladas con un modo *offline*

**Contexto.**
- Para quien observa desde fuera, un nodo caído, lento o particionado se ve igual (Conf. 1 y 3).
- Ante una partición, cada componente difunde solo lo que conoce y, al reconectarse, intercambia las novedades pendientes (Conf. 5).
- Probar solo el apagado elegante es probar el escenario más favorable (Conf. 3).

**Decisión.**
- `set_online(False)` hace que los métodos federados del servidor fallen con `ServidorNoDisponible` y pausa su entregador.
- Las operaciones locales siguen funcionando: los usuarios de ese servidor pueden publicar, y sus publicaciones se encolan.
- Al volver (`set_online(True)`), las colas se vacían en orden y el sistema converge.

**Alternativas.** `ray.kill(actor)`: simula un *crash-stop* real, pero sin persistencia (D3) se pierde todo el estado. Queda como prueba opcional junto con SQLite (F.2).

**Consecuencias.**
- Se prioriza la **disponibilidad** (CAP, Conf. 1): cada lado de la partición sigue funcionando.
- La convergencia tras reconectar es la "reconciliación" de Conf. 5: las colas de D6 guardan las novedades pendientes.

---

## D15. Sin autenticación entre servidores en la Entrega 1

**Contexto.** La protección no es un adorno que se agrega al final: es la base de la identidad de los servicios (Conf. 1). La falacia 4 es "la red es segura" (Conf. 1).

**Decisión.**
- En la Entrega 1 no hay firmas entre servidores: los actores solo son accesibles desde dentro del clúster de Ray.
- Sí se valida la **coherencia**: el `actor` de una actividad debe pertenecer al dominio del servidor que la entrega. Esto no es autenticación, porque el remitente declara su propio dominio.

**Alternativas.** Firmar las actividades ya en la Entrega 1. Agrega trabajo criptográfico que no es el foco de esta entrega.

**Consecuencias.** **Es una limitación explícita.** La entrega final agrega HTTP Signatures (firma con la clave del actor y verificación con su clave pública).

---

## D16. Directorio de servidores: el registro de nombres de Ray

**Contexto.**
- Saber qué servicio se quiere no es saber dónde vive (Conf. 1).
- Hay tres mecanismos de descubrimiento: un **registro** con autoridad, una **DHT** y **gossip** (Conf. 5).
- En Ray, el *Global Control Service* (GCS) mantiene el estado del clúster y los actores con nombre (Conf. 2).

**Decisión.**
- Un servidor se encuentra por su dominio con `ray.get_actor(dominio, namespace="bluejay")`. Es un **registro** apoyado en el GCS, el equivalente a WebFinger/DNS en la versión HTTP.
- Las referencias obtenidas se guardan en caché. Si una llamada falla con `RayActorError` (el actor murió o se reinició), la referencia se descarta y se vuelve a resolver (*stale reference*, Conf. 4).

**Alternativas.**
- *DHT:* resuelve "quién es responsable de una clave", que no es nuestro problema. Cada dominio tiene un único responsable conocido.
- *Gossip de membresía:* útil sin autoridad central, pero aquí el clúster ya tiene una.

**Consecuencias.** El GCS es un **punto crítico**: si falla, el descubrimiento sufre durante su recuperación (Conf. 2). Es aceptable en la Entrega 1. En la versión HTTP cada dominio se resuelve por DNS y no existe esa autoridad única.

---

## D17. Concurrencia dentro de los actores: asíncronos, sin `ray.get` y con *timeouts*

**Contexto.**
- Un *deadlock* necesita cuatro condiciones a la vez; una de ellas es la **espera circular** (Conf. 3). Si `alpha` espera bloqueado a `beta` mientras `beta` espera a `alpha`, ninguno avanza.
- Mantener un bloqueo mientras dura una llamada remota es un error. El patrón correcto es "capturar estado → liberar → llamar → verificar al volver" (Conf. 3).
- Una **carrera lógica** ocurre cuando se protege cada instrucción pero no la decisión completa "leer → verificar → actualizar" (Conf. 3).
- Hay que usar `ray.get(ref, timeout=X)` para no bloquearse indefinidamente (Conf. 2).

**Decisión.**
- `ServidorActor` es un **actor asíncrono** (métodos `async def`). Dentro de un actor **nunca** se llama a `ray.get()`; se usa `await` con `asyncio.wait_for(..., timeout)`.
- **Ninguna decisión "leer → verificar → actualizar" se parte con un `await` en el medio.** Si hace falta una llamada remota, primero se captura lo necesario, después se llama y, al volver, se **verifica de nuevo** el estado antes de modificarlo.

**Alternativas.** Actores síncronos con `ray.get` dentro: es más simple de leer, pero dos servidores que se consultan entre sí (por ejemplo, con D12) pueden bloquearse mutuamente.

**Consecuencias.**
- Mientras un método espera una respuesta remota, el actor atiende otras llamadas. Esto evita el *deadlock*, pero el estado puede cambiar durante el `await`, y por eso existe la regla de volver a verificar.
- La vivacidad (Conf. 3) depende de que toda espera tenga *timeout*.
