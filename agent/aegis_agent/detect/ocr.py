"""Leer el texto de una imagen. Opcional, apagado por defecto, y con presupuesto.

## Por que existe

Era el hueco mas grande del motor. Una captura de pantalla a ChatGPT o a Claude
daba NADA en las dos formas de proveedor, y es el canal que mas crece: nadie
transcribe la nomina, le saca una foto a la pantalla. El texto que acompana la
imagen --lo unico que Aegis miraba-- casi nunca dice nada sensible.

## Por que esta APAGADO por defecto, con numeros

Se midio antes de disenarlo, y lo medido cambio el diseno. Sobre una captura de
900x260 con tres lineas de texto, en CPU:

    carga del motor      ~2 s, una vez
    inferencia p50       1.7 s en una maquina descansada
                         5-9 s con la maquina ocupada

**Eso es entre dos y trece veces el presupuesto COMPLETO de T2**, que son 700 ms.
No es un modelo lento: es que el OCR es una tarea cara y no hay version barata.

Asi que la regla que gobierna a T2 --«un modelo lento no puede frenar a la
persona»-- aplica con mas fuerza todavia, y la conclusion honesta es que esto no
puede estar prendido para todo el mundo sin que la empresa lo decida. Se prende
con `AEGIS_OCR=1`.

**Y cuando esta prendido, se paga solo en un envio con imagen**, que es una accion
puntual que la persona acaba de iniciar --arrastro un archivo-- y donde ya espera
una demora. No es un tecleo. Ese es el argumento por el que el presupuesto de acá
es de segundos y el de T2 de milisegundos: no es la misma clase de momento.

## Lo que hay que saber para no sobrevender esto

**El texto que sale del OCR es aproximado, y eso tiene una consecuencia de
diseno.** En la misma medicion:

  - `Verano2026Bogota` salio como `Verano2o26Bogota` (un cero por una o).
  - `AKIAIOSFODNN7EXAMPLE` no se leyo en absoluto en la imagen chica, y si en la
    misma imagen al doble de tamano.

Entonces: **una regla de formato sobre texto de OCR es suerte.** Un caracter mal
leido y la llave de AWS deja de matchear. Lo que SI sobrevive al ruido son las
reglas contextuales --«la contrasena ... es X», «NIT» cerca de un numero--
porque les alcanza la forma de la frase y no dependen de cada caracter.

Por eso los hallazgos que salen de una imagen tendrian que tener la misma rebaja
de autoridad que los de T2, y por la misma razon: son probabilisticos. Hoy entran
por la cascada normal, y esa es una deuda anotada, no una decision.

Y de ahi sale el unico truco de preprocesamiento que se aplica: **agrandar la
imagen chica**. No es una intuicion, es lo que se midio arriba.

## La deuda que queda escrita

El modo asincronico. La subida del archivo y el turno que le pide al modelo
leerlo son DOS requests distintos --se descubrio armando `subidas.py`-- y entre
los dos hay una ventana real: la persona tiene que apretar enviar. Lo correcto
seria hacer el OCR fuera del camino critico al subir, y frenar el turno siguiente
si encontro algo. Asi la latencia no se paga nunca y la fuga igual no se completa,
porque el archivo en el blob todavia no es una fuga: la fuga es pedirle al modelo
que lo lea. Requiere estado por sesion y no entra en este cambio.
"""

from __future__ import annotations

import io
import os
import threading
import time

# Presupuesto en milisegundos. En segundos y no en milisegundos porque el OCR
# cuesta segundos: ver el encabezado. Si se pasa, se descarta el resultado y
# queda lo que vio el resto del motor, igual que con T2.
PRESUPUESTO_MS = int(os.environ.get("AEGIS_OCR_PRESUPUESTO_MS", "4000"))

# Lado minimo al que se agranda una imagen chica. Medido: la llave de AWS no se
# leyo a 900 px de ancho y si se leyo a 1800.
LADO_MINIMO = 1600
LADO_MAXIMO = 2600

# Confianza minima por caja. Abajo de esto el texto es adivinanza y solo agrega
# ruido a las reglas.
CONFIANZA_MINIMA = 0.5

# Cuanto se separan dos cajas para considerarlas de renglones distintos. Importa:
# medido, "NIT" y "900.123.456-7" salen como dos cajas, y la regla de documento
# necesita que la palabra este CERCA del numero. Sin juntar por renglon, el
# hallazgo se pierde por como el OCR corta las cajas y no por el motor.
TOLERANCIA_DE_RENGLON = 12

_motor = None
_lock = threading.Lock()
_roto = False


def habilitado() -> bool:
    return os.environ.get("AEGIS_OCR", "").strip() in ("1", "true", "si", "yes")


def disponible() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def cargar() -> object | None:
    """Carga el motor una sola vez. Devuelve None si no se puede.

    Que no este instalado no es un error: es el caso por defecto. Igual que con
    T2, el motor tiene que seguir protegiendo con todo lo demas.
    """

    global _motor, _roto
    if _motor is None and not _roto:
        with _lock:
            if _motor is None and not _roto:
                try:
                    from rapidocr_onnxruntime import RapidOCR

                    _motor = RapidOCR()
                except Exception:
                    _roto = True
    return _motor


def _preparado(datos: bytes) -> bytes:
    """La imagen escalada al rango donde el OCR mide mejor.

    Sin PIL se devuelve tal cual: el escalado mejora la lectura pero no es
    condicion para que funcione.
    """

    try:
        from PIL import Image

        imagen = Image.open(io.BytesIO(datos))
        ancho, alto = imagen.size
        lado = max(ancho, alto)
        if lado < LADO_MINIMO:
            factor = LADO_MINIMO / lado
            imagen = imagen.resize(
                (int(ancho * factor), int(alto * factor)), Image.LANCZOS
            )
        elif lado > LADO_MAXIMO:
            imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
        else:
            return datos
        buffer = io.BytesIO()
        imagen.convert("RGB").save(buffer, "PNG")
        resultado = buffer.getvalue()
    except Exception:
        resultado = datos
    return resultado


def _por_renglones(cajas) -> str:
    """Junta las cajas que estan a la misma altura, en un renglon cada una.

    Es lo que arregla el caso medido de "NIT" y "900.123.456-7" saliendo
    separados: la regla de documento de identidad necesita la palabra cerca del
    numero, y el OCR corta por caja y no por frase.
    """

    filas: list[tuple[float, list[tuple[float, str]]]] = []
    for caja in cajas:
        puntos, texto, confianza = caja[0], caja[1], caja[2]
        try:
            confianza = float(confianza)
        except (TypeError, ValueError):
            confianza = 1.0
        if confianza < CONFIANZA_MINIMA or not str(texto).strip():
            continue
        try:
            ys = [float(p[1]) for p in puntos]
            xs = [float(p[0]) for p in puntos]
            y, x = sum(ys) / len(ys), min(xs)
        except (TypeError, ValueError, IndexError, ZeroDivisionError):
            # Sin geometria usable, la caja va en su propio renglon y en el orden
            # en que vino. Se prefiere eso a descartarla: el texto es lo que
            # importa y la posicion solo sirve para juntar renglones.
            y, x = float(len(filas)), 0.0
        for altura, elementos in filas:
            if abs(altura - y) <= TOLERANCIA_DE_RENGLON:
                elementos.append((x, str(texto)))
                break
        else:
            filas.append((y, [(x, str(texto))]))

    filas.sort(key=lambda f: f[0])
    return "\n".join(
        " ".join(texto for _, texto in sorted(elementos)) for _, elementos in filas
    )


def leer(datos: bytes) -> str:
    """El texto de una imagen, o vacio si no se pudo dentro del presupuesto."""

    motor = cargar()
    if motor is None:
        return ""

    inicio = time.perf_counter()
    try:
        resultado, _ = motor(_preparado(datos))
    except Exception:
        # Una imagen corrupta o un formato que el motor no soporta no puede
        # llevarse puesto el escaneo del resto del request.
        return ""

    transcurrido = (time.perf_counter() - inicio) * 1000
    if transcurrido > PRESUPUESTO_MS or not resultado:
        # Descartar y no devolver a medias: un texto parcial produce hallazgos
        # que dependen de cuan cargada estaba la maquina, y un detector que
        # depende de eso es peor que uno que no ve.
        return ""
    return _por_renglones(resultado)


def vistas(imagenes: list[bytes]) -> list[str]:
    """El texto de cada imagen, para sumarlo a las vistas del payload.

    El presupuesto es POR IMAGEN y ademas total: cuatro imagenes de cuatro
    segundos serian dieciseis, y a esa altura la persona ya penso que Aegis rompio
    su navegador.
    """

    salida: list[str] = []
    inicio = time.perf_counter()
    for datos in imagenes:
        if (time.perf_counter() - inicio) * 1000 > PRESUPUESTO_MS:
            break
        try:
            texto = leer(datos)
        except Exception:
            # El OCR es una vista mas, no el motor. Es la misma doctrina que
            # gobierna al sensor de puntos ciegos: es visibilidad, y que falle no
            # puede llevarse puesto lo que si esta protegiendo. Sin esto, una
            # imagen que le cae mal al motor apagaba T1 entero para ese request
            # --y T1 es donde vive la certeza. Lo encontro un test.
            texto = ""
        if texto:
            salida.append(texto)
    return salida
