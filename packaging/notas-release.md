Aegis se pone entre tu computadora y los servicios de IA —ChatGPT, Claude, Copilot, Gemini y unos ciento setenta más— y revisa **en tu propio equipo** si lo que estás por enviar contiene información que no debería salir.

Cuando encuentra algo, te lo explica antes de que salga.

## Cuál descargar

| | Peso | Qué detecta |
|---|---|---|
| **`Aegis-windows.zip`** | 103 MB | Credenciales, documentos, tarjetas, capturas de pantalla. Es el que querés para probar. |
| `Aegis-windows-completo.zip` | 1,2 GB | Todo lo anterior **más el modelo local**, que es lo único que ve los datos de empresa: *"el margen con Alpina quedó en 4%"*. Las reglas ven 0 de 14 de esos casos; el modelo es lo que los cubre. |

El completo trae el modelo adentro y viene prendido: no descarga nada en el primer uso.

## Para instalarlo

1. Descargá el zip y descomprimilo donde quieras.
2. Doble clic en **`Instalar Aegis.bat`**.
3. Windows te va a pedir permiso para confiar en el certificado de Aegis. Hay que **aceptar**: sin eso, cada sitio seguro te muestra una advertencia.
4. Si tu empresa te dio un código, pegalo cuando te lo pida. Ese equipo empieza a reportar a su panel.

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

Requiere Windows. 109 MB comprimido, 249 MB en disco. Incluye la lectura de texto en imágenes (apagada por defecto, se prende desde el panel).
