Aegis se pone entre tu computadora y los servicios de IA —ChatGPT, Claude, Copilot, Gemini y unos ciento setenta más— y revisa **en tu propio equipo** si lo que estás por enviar contiene información que no debería salir.

Cuando encuentra algo, te lo explica antes de que salga.

## Qué se descarga

`Aegis-windows.zip` — 1,2 GB.

Trae las reglas deterministas, el diccionario de tu empresa, la lectura de texto en imágenes **y el modelo local**, que es lo único que ve los datos de negocio: *"el margen con Alpina quedó en 4%"*. Sobre el banco de pruebas, las reglas ven 0 de 14 de esos casos y el modelo es lo que los cubre.

El modelo viaja adentro y viene prendido: no descarga nada la primera vez que lo usás, ni te sorprende con un giga en el primer envío.

## Para instalarlo

1. Descargá el zip y descomprimilo donde quieras.
2. Doble clic en **`Instalar Aegis.bat`**.
3. Windows te va a pedir permiso para confiar en el certificado de Aegis. Hay que **aceptar**: sin eso, cada sitio seguro te muestra una advertencia y Aegis no se activa.

Desde ahí ya estás protegido, y arranca solo cada vez que iniciás sesión.

## Para conectarlo con tu empresa

Si tu empresa usa Aegis, pedile el código al administrador —son cuatro letras o números, un guion, y otros cuatro— y hacé doble clic en **`Conectar con mi empresa.bat`**.

Son dos pasos separados a propósito: **instalar** decide si este equipo está protegido, **conectar** decide a quién le reporta y de quién recibe la configuración. Podés hacerlos en cualquier orden.

Sin conectar, Aegis igual te protege: bloquea, avisa y te explica. Lo que no pasa es que tu empresa se entere, ni que te lleguen sus políticas —sus términos internos, qué herramientas están aprobadas, qué se bloquea y qué solo se avisa—.

## Los otros lanzadores

| Archivo | Para qué |
|---|---|
| `Panel de Aegis.bat` | Ver qué revisó, y prenderlo o apagarlo |
| `Estado de Aegis.bat` | Si está protegiendo ahora mismo |
| `Desinstalar Aegis.bat` | Sacarlo del equipo, sin dejar nada |

También aparece en "Agregar o quitar programas".

## Lo que Aegis *no* hace

- **No manda lo que escribís a ningún servidor.** La decisión de bloquear se toma completa en tu equipo, sin conexión. Lo único que sale es un aviso sin contenido: *"salió una credencial hacia tal sitio"*, nunca el texto.
- **No mira tu banco, tu prestadora de salud ni las páginas del gobierno.** Esas conexiones ni se abren.
- **No necesita permisos de administrador** y no cambia nada a nivel de la máquina. Todo queda en tu usuario.

## Si algo sale mal

Si en algún momento no tenés internet, es porque el navegador apunta a Aegis y Aegis no está corriendo. Corré `Estado de Aegis.bat`: te lo dice en una línea. Y `Desinstalar Aegis.bat` te devuelve todo como estaba, siempre.

---

Requiere Windows. 1,2 GB comprimido. Incluye el modelo local (prendido) y la lectura de texto en imágenes (apagada por defecto, se prende desde el panel).
