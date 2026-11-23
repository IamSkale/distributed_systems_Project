"""Transporte en el mismo proceso: varios `ServidorBlueJay` que se pasan las entregas a mano.

Hace, de forma síncrona y determinista, lo que harán los actores de Ray (Etapa D):

- una cola FIFO de entregas; las de un servidor desconectado (como destino o como
  remitente) quedan retenidas en orden hasta que vuelva (D6, D14);
- una actividad rechazada por el receptor (`ActividadInvalida`) va a *dead letter* sin
  reintentos (*poison pill*, Conf. 4);
- las republicaciones que esperan a su original se resuelven pidiéndolo al origen con
  `servir_objeto` (D12).

No tiene reintentos con *backoff* ni colas acotadas: eso es del `EntregadorActor`. Sirve
para las pruebas del núcleo y para que el frontend trabaje antes de que exista la capa de Ray.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from bluejay.dominio.actividades import ActividadInvalida
from bluejay.dominio.modelos import Entrega, dominio_de
from bluejay.dominio.servidor import Resultado, ServidorBlueJay


@dataclass(frozen=True, slots=True)
class DeadLetter:
    remitente: str
    entrega: Entrega
    motivo: str


class RedLocal:
    def __init__(self, *dominios: str) -> None:
        self.servidores = {d: ServidorBlueJay(d) for d in dominios}
        self.cola: deque[tuple[str, Entrega]] = deque()  # (dominio remitente, entrega)
        self.desconectados: set[str] = set()
        self.entregadas: list[tuple[str, Entrega]] = []
        self.dead_letters: list[DeadLetter] = []

    def __getitem__(self, dominio: str) -> ServidorBlueJay:
        return self.servidores[dominio]

    def hacer[T](self, dominio: str, resultado: Resultado[T]) -> T:
        """Encola las entregas de una operación de `dominio`, las propaga y devuelve su valor."""
        self.encolar(dominio, resultado.entregas)
        self.propagar()
        return resultado.valor

    def encolar(self, remitente: str, entregas: list[Entrega]) -> None:
        self.cola.extend((remitente, e) for e in entregas)

    def desconectar(self, dominio: str) -> None:
        self.desconectados.add(dominio)

    def reconectar(self, dominio: str) -> None:
        self.desconectados.discard(dominio)
        self.propagar()

    def pendientes(self, dominio: str | None = None) -> list[tuple[str, Entrega]]:
        """Entregas retenidas; con `dominio`, solo las que salen de ese servidor."""
        return [(r, e) for r, e in self.cola if dominio is None or r == dominio]

    def propagar(self) -> None:
        """Entrega todo lo posible hasta que no quede nada que avance."""
        avanzo = True
        while avanzo:
            avanzo = False
            retenidas: deque[tuple[str, Entrega]] = deque()
            while self.cola:
                remitente, entrega = self.cola.popleft()
                if entrega.destino in self.desconectados or remitente in self.desconectados:
                    retenidas.append((remitente, entrega))
                    continue
                avanzo = True
                if entrega.destino not in self.servidores:
                    self.dead_letters.append(DeadLetter(remitente, entrega, "servidor desconocido"))
                    continue
                try:
                    respuesta = self[entrega.destino].procesar(entrega.actividad, remitente)
                except ActividadInvalida as error:
                    self.dead_letters.append(DeadLetter(remitente, entrega, str(error)))
                    continue
                self.entregadas.append((remitente, entrega))
                self.encolar(entrega.destino, respuesta)
            self.cola = retenidas
            avanzo |= self._resolver_dependencias()

    def _resolver_dependencias(self) -> bool:
        avanzo = False
        for dominio, servidor in self.servidores.items():
            if dominio in self.desconectados:
                continue
            for uri in servidor.dependencias_pendientes():
                origen = dominio_de(uri)
                if origen in self.desconectados:
                    continue  # la capa de Ray reintentará con backoff
                objeto = self[origen].servir_objeto(uri, dominio) if origen in self else None
                if objeto is None:
                    servidor.descartar_dependencia(uri)
                else:
                    servidor.recibir_objeto(objeto, origen)
                avanzo = True
        return avanzo

    def __contains__(self, dominio: object) -> bool:
        return dominio in self.servidores

    def tipos_entregados(self, destino: str) -> list[str]:
        return [e.actividad["type"] for _, e in self.entregadas if e.destino == destino]
