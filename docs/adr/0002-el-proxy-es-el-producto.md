# ADR 0002 — El proxy es el producto; las integraciones por aplicación son opcionales

- **Estado:** aceptado
- **Fecha:** 2026-08-22
- **Complementa:** [ADR 0001](0001-interceptar-en-el-endpoint-por-capas.md)
- **Contexto:** [Investigación 01](../research/01-interceptacion-de-trafico.md), [Investigación 02](../research/02-motor-de-deteccion.md)

## Contexto

El ADR 0001 listó cinco capas de intercepción y presentó el hook de Claude Code como la demo
principal. Eso desbalanceó el mensaje: dio a entender que la cobertura se construye
**aplicación por aplicación**. No es así, y no puede serlo — el objetivo es toda la IA que corra en
la computadora, incluida la que todavía no existe y la que nadie aprobó.

Un enfoque por aplicación no escala por tres razones: hay que escribir una integración por
herramienta, se rompe cuando la herramienta cambia, y deja fuera exactamente el caso más peligroso
— la app que el equipo de seguridad no sabe que está instalada.

## Decisión

**La cobertura la da el punto de intercepción, no la aplicación.** El proxy local con CA propia es
el producto. Las integraciones nativas por herramienta (hooks de Claude Code, `ANTHROPIC_BASE_URL`)
son *mejoras opcionales* sobre herramientas concretas, nunca la base de la cobertura.

En consecuencia:

1. El motor de detección **no sabe qué aplicación originó el tráfico**. Recibe texto y un destino,
   y decide. Eso es lo que hace que el mismo código cubra ChatGPT en el navegador, Cursor, un
   script de Python o una app de escritorio desconocida.
2. Las integraciones nativas se justifican solo por lo que agregan *encima* de la cobertura base:
   contexto estructurado y un canal de vuelta para mostrar la lección dentro de la propia
   herramienta. Si desaparecieran, Aegis seguiría funcionando.
3. Para las aplicaciones que ignoran el proxy del sistema y no leen variables de entorno, la
   respuesta es redirección forzada — y en Windows hay una vía **user-mode** que no exige escribir
   un driver: WinDivert (trae su propio driver firmado; ProxyBridge y shadow son implementaciones
   de referencia que redirigen TCP/UDP por proceso). Eso mueve esa capa de "imposible en el
   hackathon" a "posible en Windows si sobra tiempo". Tiene límites conocidos y documentados:
   Windows aplica anti-spoofing por debajo de WinDivert, y hay casos reportados de fallos sobre
   Wi-Fi que funcionan sobre Ethernet.
4. Toda aplicación que el sensor de conexiones vea hablando con un dominio de IA y que el proxy
   nunca haya interceptado se reporta como **tráfico no inspeccionable**. Es una alerta visible del
   producto, no un silencio.

## Razones

- El valor que se le vende a la empresa es "ninguna de tus herramientas de IA puede filtrar datos",
  no "Claude Code no puede filtrar datos".
- El shadow AI —el problema que el producto dice atacar— es por definición la herramienta para la
  que nadie escribió una integración.
- Un detector que ignora el origen es más simple, más testeable y más fácil de auditar que uno con
  una rama por aplicación.

## Consecuencias

**A favor**

- Una sola implementación cubre todo lo que respete proxy o variables de entorno: navegadores, apps
  Electron, IDEs, CLIs y scripts.
- El producto cubre herramientas de IA que aún no existen sin tocar código.

**En contra**

- La demo pierde el atajo cómodo del hook y obliga a tener el proxy funcionando de punta a punta
  para mostrar cualquier cosa. Es más trabajo antes de la primera demo, y hay que asumirlo.
- Quedan huecos reales (pinning, QUIC, apps que ignoran el proxy). La respuesta honesta es
  detectarlos y mostrarlos, no fingir cobertura total.

## Nota sobre el modelo local

Discusión aparte, resuelta en la [Investigación 02](../research/02-motor-de-deteccion.md): correr un
LLM local para analizar todo lo que se envía **no** es el diseño. El destino filtra primero (queda
un 1-3% del tráfico), y sobre ese resto corre una cascada barato → caro donde lo local son reglas
deterministas y un encoder pequeño cuantizado, y el LLM aparece solo para lo ambiguo y para generar
la lección de forma asíncrona. Un LLM local completo queda como modo *air-gapped* para clientes
regulados, no como requisito del MVP.
