from __future__ import annotations

import threading
from collections import defaultdict

# Un servicio de IA no se delata por su nombre. monica.im, coze.com o el
# asistente que alguien monto el martes no dicen "IA" en ninguna parte, y ahi
# vive el shadow AI de verdad: en el dominio que ninguna lista tiene y que
# tampoco parece nada.
#
# Lo que si delata a un modelo es como se comporta. Estas son las senales que se
# observan localmente, sin mandar nada a ningun lado, y solo cuando un dominio
# junta suficientes se pide su clasificacion.

# Streaming por Server-Sent Events. Es la huella mas fuerte que existe: casi
# ningun servicio normal responde asi, y practicamente todos los chats con
# modelo lo hacen para ir mostrando la respuesta palabra por palabra.
PESO_STREAMING = 3

# El request tiene forma de llamada a un modelo (ruta o claves del cuerpo).
PESO_FORMA = 2

# Se envio un bloque largo de texto libre, que es lo que uno le manda a un
# modelo y casi nunca a un formulario.
PESO_TEXTO_LARGO = 1

# Salio un dato sensible (T1: llave, token, tarjeta) hacia un dominio que
# todavia no se sabe si es una IA. Es la senal mas fuerte que existe para
# pedir la clasificacion: si algo asi salio, el destino merece que lo
# investiguen sin importar como se comporte el resto del trafico.
PESO_DATO_SENSIBLE = 3

# Con esto alcanza para pedir la clasificacion. Un solo streaming basta; dos
# senales debiles tambien.
UMBRAL = 3

# Debajo de esto es un campo de formulario, no una conversacion.
MIN_TEXTO_LARGO = 280

TIPOS_STREAMING = ("text/event-stream", "application/x-ndjson")


class SignalCollector:
    """Cuenta senales de comportamiento por dominio, en memoria y local.

    No persiste nada: si el agente se reinicia, se vuelven a juntar. Guardar en
    disco que dominios visita cada persona seria construir justo el registro que
    este producto promete no tener.
    """

    def __init__(self, umbral: int = UMBRAL) -> None:
        self.umbral = umbral
        self._lock = threading.Lock()
        self._puntajes: dict[str, int] = defaultdict(int)
        self._motivos: dict[str, set[str]] = defaultdict(set)
        self._reportados: set[str] = set()

    def _sumar(self, domain: str, peso: int, motivo: str) -> None:
        with self._lock:
            self._puntajes[domain] += peso
            self._motivos[domain].add(motivo)

    def observe_request(self, domain: str, tiene_forma_de_ia: bool, texto: str) -> None:
        if tiene_forma_de_ia:
            self._sumar(domain, PESO_FORMA, "el request tiene forma de llamada a un modelo")
        if len(texto) >= MIN_TEXTO_LARGO:
            self._sumar(domain, PESO_TEXTO_LARGO, "se envio un bloque largo de texto libre")

    def observe_response(self, domain: str, content_type: str) -> None:
        normalizado = content_type.lower()
        if any(tipo in normalizado for tipo in TIPOS_STREAMING):
            self._sumar(domain, PESO_STREAMING, "responde con streaming, como un modelo")

    def observe_sensitive_egress(self, domain: str) -> None:
        self._sumar(domain, PESO_DATO_SENSIBLE, "salio un dato sensible hacia aca")

    def score(self, domain: str) -> int:
        with self._lock:
            return self._puntajes.get(domain, 0)

    def reasons(self, domain: str) -> list[str]:
        with self._lock:
            return sorted(self._motivos.get(domain, set()))

    def should_classify(self, domain: str) -> bool:
        """Verdadero una sola vez por dominio, cuando cruza el umbral.

        Devolver verdadero muchas veces haria que el agente pidiera lo mismo en
        cada peticion, y el backend recibiria una tormenta por cada pestana.
        """

        with self._lock:
            listo = (
                self._puntajes.get(domain, 0) >= self.umbral
                and domain not in self._reportados
            )
            if listo:
                self._reportados.add(domain)
        return listo

    def pending(self) -> list[tuple[str, int]]:
        with self._lock:
            return sorted(
                ((dominio, puntaje) for dominio, puntaje in self._puntajes.items()),
                key=lambda fila: -fila[1],
            )
