"""El aviso en la pantalla de la persona, cuando la aplicacion no lo muestra.

Aegis ya le contesta a cada cliente en el idioma que ese cliente entiende: al
navegador una pagina con la leccion, y a una aplicacion un 403 con
`{"error":{"message": ...}}`, que es la forma exacta que usan las APIs de
Anthropic y de OpenAI y que sus SDKs saben levantar.

El problema es que ahi se termina nuestro control. Que la UI de una app de
escritorio pinte ESE texto o un "algo salio mal" generico es decision de esa
app, y no hay contrato que lo garantice. Cuando se lo come, la persona ve que su
mensaje fallo y no tiene una sola pista de que fue Aegis ni de por que, que es
justamente el escenario que el producto existe para evitar: un bloqueo que no se
entiende no ensena nada y se siente como una falla de la herramienta.

Asi que en ese caso --y solo en ese-- Aegis pone un aviso del sistema. Al
navegador no, porque ya recibio la pagina completa y dos avisos por el mismo
bloqueo es ruido.

## Por que PowerShell y no una libreria

Porque esto se empaqueta con PyInstaller y cada dependencia nueva entra al zip.
El toast de Windows se pide por WinRT, que ya viene en el sistema. El texto
viaja por variables de entorno y no interpolado en el script: es lo que evita
que un mensaje con una comilla rompa el comando.

## Reglas

- Nunca lanza. Un aviso que falla no puede tumbar el proxy ni cambiar una
  decision: cuando esto corre, el bloqueo ya esta resuelto.
- Nunca en el camino critico. Sale en un hilo aparte y en un proceso suelto.
- Con pausa. Una sola pantalla de chat reintenta el envio varias veces; sin
  pausa serian diez notificaciones por el mismo secreto.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

# Cuanto se espera antes de volver a avisar por la misma app y el mismo destino.
PAUSA = 20.0

# Lo que entra en un toast sin quedar cortado a la mitad por Windows.
MAX_CUERPO = 220

_TITULO = "Aegis freno un envio"

_lock = threading.Lock()
_ultimo: dict[tuple[str, str], float] = {}

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
  $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $t = $x.GetElementsByTagName('text')
  $t.Item(0).AppendChild($x.CreateTextNode($env:AEGIS_AVISO_TITULO)) | Out-Null
  $t.Item(1).AppendChild($x.CreateTextNode($env:AEGIS_AVISO_CUERPO)) | Out-Null
  $n = [Windows.UI.Notifications.ToastNotification]::new($x)
  $id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($n)
} catch { }
"""


def habilitado() -> bool:
    """Se puede apagar, y la suite lo apaga.

    Viene prendido porque es la unica garantia de que la persona se entere: si
    hubiera que activarlo, en la practica nadie lo activaria y el caso que este
    modulo cubre volveria a quedar descubierto.
    """

    return os.environ.get("AEGIS_AVISO", "1").strip().lower() not in ("0", "false", "no")


def _texto_corto(mensaje: str) -> str:
    """El mensaje completo no cabe: se queda la leccion, no el preambulo.

    El mensaje que recibe la app empieza con "Aegis bloqueo el envio: " porque
    ahi hace falta decir quien habla. En el toast eso ya lo dice el titulo, asi
    que repetirlo gasta la unica linea que hay.
    """

    texto = " ".join((mensaje or "").split())
    for prefijo in ("Aegis bloqueo el envio:", "Aegis bloqueo la conexion:"):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):].strip()
            break
    if len(texto) > MAX_CUERPO:
        texto = texto[: MAX_CUERPO - 1].rstrip(" ,.;:") + "…"
    return texto


def _debe_avisar(app: str, host: str, ahora: float) -> bool:
    with _lock:
        clave = (app, host)
        if ahora - _ultimo.get(clave, 0.0) < PAUSA:
            return False
        _ultimo[clave] = ahora
        return True


def _mostrar(titulo: str, cuerpo: str) -> None:
    """Lanza el toast y se olvida. Cualquier error se traga a proposito."""

    try:
        banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
            env={**os.environ, "AEGIS_AVISO_TITULO": titulo, "AEGIS_AVISO_CUERPO": cuerpo},
            creationflags=banderas,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:
        pass


def avisar_bloqueo(mensaje: str, app: str = "", host: str = "") -> bool:
    """Avisa en la pantalla que Aegis freno un envio. Devuelve si lo intento.

    El booleano existe para los tests y para `aegis estado`: sirve para saber si
    la pausa lo salteo o si el aviso esta apagado, sin tener que mirar la
    pantalla.
    """

    if not habilitado() or sys.platform != "win32":
        return False
    if not _debe_avisar(app or "?", host or "?", time.time()):
        return False

    donde = f" desde {app}" if app and app != "desconocido" else ""
    titulo = f"{_TITULO}{donde}"
    cuerpo = _texto_corto(mensaje) or "El envio no salio de tu equipo."
    threading.Thread(target=_mostrar, args=(titulo, cuerpo), daemon=True).start()
    return True


def olvidar() -> None:
    """Vacia la pausa. Para los tests."""

    with _lock:
        _ultimo.clear()
