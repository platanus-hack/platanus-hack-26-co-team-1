# ADR 0004 — La política conoce la aplicación; el detector no

- **Estado:** aceptado
- **Fecha:** 2026-08-22
- **Matiza:** [ADR 0002](0002-el-proxy-es-el-producto.md)

## Contexto

El ADR 0002 dice, y sigue vigente: *"el motor de detección **no sabe qué aplicación originó el
tráfico**. Recibe texto y un destino, y decide."* Es lo que hace que el mismo código cubra ChatGPT
en el navegador, un IDE, un script y una herramienta que todavía no existe.

Pero el contrato de datos define `destination.process` desde el primer día, y el agente lo estaba
rellenando con la constante `"browser"`. **Todos los eventos mentían.** El panel no podía distinguir
a una persona pegando un fragmento de un agente de código mandando un repositorio entero, que en
2026 es exactamente la diferencia que importa.

Y apareció el caso que lo forzó, con un empleado real: un desarrollador trabajando sobre un
repositorio cuyos *fixtures* contienen credenciales de prueba queda bloqueado por su propio código,
todo el día. Le pasó al equipo de Aegis con `bench/corpus.py`, que contiene contraseñas de prueba
**a propósito**, porque son las que validan la regla que las detecta.

Las salidas malas que se descartaron:

- **Excepciones por palabra** (`test`, `example`, `fixture` cerca del valor): frágil y evadible.
  Quien quiera exfiltrar escribe "test" al lado y listo.
- **Lista de valores conocidos** (`AKIAIOSFODNN7EXAMPLE` y compañía): cubre los ejemplos de la
  documentación de AWS, no las credenciales de prueba de cada empresa.
- **Bajar la severidad de la regla:** paga el problema con menos protección para todo el mundo.

## Decisión

**La atribución por proceso existe, y llega hasta la política — nunca hasta el detector.**

Tres capas, y el límite está entre la segunda y la tercera:

1. **Detección** (`detect/`): recibe texto y destino. **No cambia.** Sigue sin saber quién envió.
2. **Evento** (`events.py`): `destination.process` dice la verdad. Es visibilidad, y el contrato ya
   la pedía.
3. **Política** (`policy.py`): `app_actions` permite poner una aplicación nombrada en modo
   `observar` — registra todo, no corta nada.

La regla que sostiene que esto no contradiga al ADR 0002:

> **Nombrar una aplicación solo puede aflojarla, nunca endurecerla, y lo desconocido se queda con lo
> estricto.**

Hay que nombrar una app para que deje de cortar. La herramienta de IA que el equipo de seguridad no
sabe que está instalada —el caso que el ADR 0002 protege— sigue tratada como lo que es. Si la
atribución falla (sin `psutil`, sin permisos, conexión ya cerrada), el resultado es `desconocido`, y
`desconocido` es estricto.

## Razones

- **La cobertura no baja.** Lo que se agrega es una excepción explícita, auditable y por defecto
  vacía, no una heurística que decide sola.
- **Un modo observación no pierde visibilidad**, que es lo que se estaba protegiendo: el evento se
  registra igual y llega al panel. Lo que se pierde es el corte, no la vista.
- **La alternativa real no era "bloquear siempre", era "desinstalar".** Un desarrollador bloqueado
  por sus propios fixtures apaga el proxy, y ahí la cobertura no baja: se va a cero.
- El nombre se **normaliza** (`claude.exe` y `node.exe …cli.js` son los dos `claude-code`), porque
  si no la política de la empresa dependería de cómo instaló cada quien la herramienta.

## Consecuencias

**A favor**

- El panel puede mostrar el shadow AI **por aplicación**, que es la pregunta que hace un CISO.
- Se puede desplegar Aegis en modo observación por app antes de empezar a cortar, que es como se
  despliega cualquier DLP en una empresa real.
- La atribución cuesta una lectura de la tabla de conexiones **por conexión TCP**, no por request
  (~3 ms sobre 341 conexiones, medido). Con keep-alive, una sesión entera de un CLI paga una.

**En contra, y hay que decirlo**

- **Un proceso se puede renombrar.** Alguien que llame `claude.exe` a su herramienta de exfiltración
  hereda el modo observación. Hoy se mitiga con que la regla es opt-in y con que el evento guarda
  también la ruta del ejecutable; la mitigación de verdad es firmar por ruta o por firma digital, y
  no está hecha.
- Depende de `psutil` y de poder enumerar procesos ajenos. Sin eso no hay atribución — y no hay
  degradación de la protección, solo del panel.
- El modo `observar` **es** menos protección para esa aplicación. Es una decisión de la empresa, y
  por eso vive en la política y no en el código.
