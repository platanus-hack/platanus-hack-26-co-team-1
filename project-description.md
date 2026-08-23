# Aegis

**El 80% de las fugas hacia IA pasan por el navegador. El otro 20% ni siquiera
tiene una pantalla: es un agente leyendo tu repositorio.**

Aegis se pone entre tu computadora y los servicios de IA, revisa **en tu propio
equipo** lo que estás por enviar, y si encuentra algo que no debería salir te lo
explica antes de que salga.

## Lo que lo hace distinto

**Decide local, enseña remoto.** El bloqueo se resuelve en el equipo, sin
conexión. Lo único que viaja al panel de la empresa es un aviso redactado:
*"salió una credencial de AWS hacia tal dominio"*, nunca el texto. No es una
promesa de marketing — la tabla **no tiene una columna donde poner el
contenido**, así que la garantía se audita leyendo veinte líneas de SQL.

**Bloquear no enseña. Aegis enseña.** Un DLP normal dice "bloqueado" y la
persona busca cómo esquivarlo. Aegis dice:

> Credencial de AWS detectada en el envío. Reemplazá esa credencial por una
> variable de entorno. **Si ya la usaste en otro lugar, rotala en la consola de
> AWS ahora mismo.**

**Ve lo que un DLP de navegador no puede ver.** Aegis vive en el socket, no en
una extensión: ve Claude Code, Cursor, los MCP y cualquier CLI. Sabe **qué
aplicación** abrió cada conexión leyendo la tabla del sistema operativo.

**Aprobar la herramienta no es aprobar la cuenta.** Todo el mercado permite por
dominio. Si la empresa aprueba ChatGPT, la cuenta personal gratuita del empleado
entra por el mismo dominio — y es la que entrena con lo que le peguen. Aegis
distingue una de otra.

## Cómo detecta

Tres capas, y cada una cubre lo que la anterior no puede:

| Capa | Qué ve | Medido |
|---|---|---|
| 28 reglas deterministas | Lo que tiene **formato**: llaves, tarjetas, cédulas | 8/8 credenciales, **0 falsos positivos** en 54 frases de trabajo normal |
| Modelo local (~50M, CPU) | Lo que tiene **sentido**: "el margen con Alpina quedó en 4%" | Las reglas ven **0 de 14** de estos casos. El modelo es lo único que los ve |
| Diccionario de la empresa | Lo que **solo esa empresa** sabe que es suyo | Ningún detector genérico puede tenerlo |

Más OCR para capturas de pantalla — nadie transcribe la nómina, le saca una
foto — y detección de inyección de prompts en las dos direcciones.

## El shadow AI que no está en ninguna lista

Sale un modelo nuevo cada semana. Aegis no depende de conocerlo: si el cuerpo
tiene forma de conversación con un modelo (`messages`, `model`, `temperature`),
lo trata como IA aunque el dominio no exista en ningún catálogo. Se puede
cambiar el dominio; no se puede cambiar el protocolo.

## Verificado, no prometido

Probado contra `api.anthropic.com` real, desde una máquina real:

```
archivo con credenciales  ->  403  cortado por Aegis
prompt limpio             ->  401  salió y contestó Anthropic
sitio de trabajo normal   ->  200  no se interrumpe
```

Ese contraste es la prueba: uno se cortó acá, el otro salió de verdad.

**877 tests.** Y una garantía que se puede correr: los eventos registrados no
contienen el secreto, y hay un test que lo verifica sobre tráfico real.

## Probalo

1. [Descargar Aegis para Windows](https://github.com/platanus-hack/platanus-hack-26-co-team-1/releases/latest)
2. Doble clic en `Instalar Aegis.bat`
3. Panel en <https://aegis-panel.onrender.com>

No pide administrador, no toca nada a nivel de la máquina, y se desinstala con
un clic desde "Agregar o quitar programas".
