# ADR 0001 — Interceptar en el endpoint, por capas

- **Estado:** aceptado
- **Fecha:** 2026-08-22
- **Contexto:** Investigación 01 (fuera del repo, ver README)

## Contexto

Aegis tiene que poder decidir, antes de que la información salga del equipo, si lo que se está
enviando es sensible y si el destino es un servicio de IA. Eso obliga a elegir **dónde** se
intercepta el tráfico. Hay tres lugares posibles: la red (firewall, DNS), el endpoint (el equipo del
empleado) o la aplicación (extensión, hook, gateway).

## Decisión

**Se intercepta en el endpoint, con una arquitectura de capas**, y no en la red.

Para el MVP se implementan tres capas:

| Capa | Qué cubre | Rol |
|---|---|---|
| **A — Integración nativa del agente** | Claude Code (hooks `UserPromptSubmit` y `PreToolUse`) | Demo principal y canal pedagógico |
| **C — Proxy MITM local con CA propia** | Codex, navegadores, Electron y todo lo que respete proxy o variables de entorno | Motor de inspección |
| **E — Sensor de conexiones por proceso** | Todo el equipo, solo destino | Descubrimiento de shadow AI |

La capa D (redirección forzada a nivel de sistema operativo: WFP en Windows,
`NETransparentProxyProvider` en macOS, eBPF en Linux) queda **fuera del MVP** y se presenta como
roadmap.

## Razones

1. **La red ya no ve lo suficiente.** Con TLS 1.3 y ECH el SNI deja de ser visible, y QUIC saca el
   tráfico del alcance de cualquier proxy TCP. Una solución de red envejece mal; el endpoint ve el
   texto antes de que se cifre.
2. **Los agentes de IA están documentados para esto.** Anthropic y OpenAI publican oficialmente cómo
   confiar en la CA de un proxy corporativo (`NODE_EXTRA_CA_CERTS`, `CLAUDE_CODE_CERT_STORE`,
   `CODEX_CA_CERTIFICATE`) y Claude Code expone hooks que pueden bloquear. El camino no es un hack.
3. **La capa D no cabe en un hackathon.** Exige un driver firmado con EV en Windows y un entitlement
   aprobado por Apple en macOS — semanas de trámite, no horas.
4. **Las capas degradan bien.** Si el proxy no ve una conexión pero el sensor sí, eso no es un punto
   ciego: es una señal de evasión que el producto debe reportar.

## Consecuencias

**A favor**

- El bloqueo en Claude Code se ve dentro del propio CLI, con el mensaje pedagógico en el mismo lugar
  donde ocurrió el error. Esa es la demo.
- Cobertura amplia sin escribir una sola línea de código en kernel.
- Funciona igual en cualquier red: café, casa, VPN.

**En contra**

- Instalar una CA en el almacén raíz exige consentimiento del usuario, y en algunos casos permisos
  de administrador. Se asume como parte del onboarding.
- Las aplicaciones con *certificate pinning* fallarán si se las intercepta: hace falta una lista de
  passthrough por dominio desde el día uno.
- Gemini en Chrome se escapa por QUIC salvo que se bloquee UDP/443 o se aplique la política
  `QuicAllowed=false`.
- Existe un hueco conocido: apps que ignoran el proxy del sistema y no leen variables de entorno.
  Se detecta con la capa E y se cierra con la capa D en el futuro.

**Obligaciones que esta decisión impone**

- `NO_PROXY` con categorías sensibles (banca, salud, actualizaciones del sistema operativo) es
  requisito de producto, no opcional.
- La clave privada de la CA se genera en el equipo y nunca sale de él. Nunca se distribuye una CA
  común entre clientes.
