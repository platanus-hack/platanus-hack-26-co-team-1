# Investigación 01 — Cómo saber a qué URL se está enviando información, desde cualquier aplicación

**Pregunta que responde este documento:** ¿cómo logramos estar al tanto, no solo en el navegador
sino en cualquier conexión a internet de cualquier aplicación de escritorio, de a qué URL se está
enviando información — y poder evitar que salgan datos privados hacia una IA?

**Respuesta corta:** no existe un único mecanismo que cubra todo. Se resuelve con **capas**, y la
decisión clave es que la intercepción vive en el **endpoint** (el equipo del empleado), no en la red.
Para el MVP la combinación ganadora es *proxy MITM local con CA propia* + *puntos de integración
nativos de los agentes de IA* + *sensor de conexiones para descubrimiento*.

---

## 1. Lo primero: hay dos niveles de información, y cuestan muy distinto

| Nivel | Qué responde | Cómo se obtiene | ¿Requiere romper TLS? |
|---|---|---|---|
| **Nivel 1 — el destino** | ¿A qué dominio/IP está hablando este proceso? | SNI del ClientHello, consultas DNS, tabla de conexiones TCP con PID | **No** |
| **Nivel 2 — el contenido** | ¿Qué texto/archivo va dentro del request? | Terminar el TLS con una CA propia instalada en el equipo (MITM) | **Sí** |

Aegis necesita los dos: el Nivel 1 alimenta la **lista negra colaborativa** y el descubrimiento de
shadow AI; el Nivel 2 es lo único que permite decir "esto que estás mandando es una API key".

Consecuencia de diseño: el Nivel 1 se puede tener sobre *todo* el tráfico del equipo con poco
esfuerzo; el Nivel 2 solo sobre el tráfico que logremos hacer pasar por nuestro proxy. La
arquitectura debe degradar con elegancia — si no podemos ver el contenido, al menos registramos el
destino y lo reportamos como *tráfico no inspeccionable*.

---

## 2. Las cinco capas posibles, comparadas

| # | Capa | Cobertura | ¿Ve el contenido? | Fricción de instalación | Viable en 48h |
|---|---|---|---|---|---|
| A | **Integración nativa del agente** (hooks de Claude Code, `ANTHROPIC_BASE_URL`) | Solo esa herramienta | Sí, en claro y con contexto estructurado | Nula (archivo de config) | **Sí** |
| B | **Extensión de navegador** (MV3) | Solo navegadores | Sí, antes de que salga (fetch/DOM/paste) | Baja (política de Chrome Enterprise) | Sí |
| C | **Proxy MITM local + CA propia** | Toda app que respete proxy o variables de entorno | Sí | Media (instalar CA + configurar) | **Sí** |
| D | **Redirección forzada a nivel de SO** (WFP / NetworkExtension / eBPF) | **Todo** el tráfico TCP, incluso apps que ignoran el proxy | Sí (combinada con C) | Alta (driver firmado, entitlements) | No |
| E | **Sensor de conexiones por proceso** | Todo el equipo | No, solo destino | Baja | **Sí** |
| F | Red / DNS (firewall, DNS filtering) | Todo el dispositivo | No | N/A (infra) | No aplica |

> **Cuál de estas capas es el producto.** La cobertura la da **C**, porque intercepta por destino y
> no por aplicación: el mismo código cubre ChatGPT en el navegador, Cursor, un script de Python o
> una app de escritorio que nadie sabe que está instalada. La capa **A** es una *mejora opcional*
> sobre herramientas concretas — agrega contexto y un canal de vuelta, pero no se construye
> cobertura herramienta por herramienta, porque el shadow AI es justamente aquella para la que
> nadie escribió una integración. Ver [ADR 0002](../adr/0002-el-proxy-es-el-producto.md).

La capa D es la que uno imagina cuando dice "interceptar todo", y es lo que hacen Zscaler, Netskope
o CrowdStrike. Es también la que **no** se construye en un fin de semana: en macOS un
`NETransparentProxyProvider` exige un *system extension* con entitlement aprobado por Apple, y en
Windows un callout driver de WFP exige firma EV y atestación. Se diseña ahora y se implementa
después; en el MVP se cubre el 90% del valor con A + C + E.

---

## 3. Capa por capa

### A. Integración nativa del agente — el punto más barato y el más profundo

Es contraintuitivo, pero el mejor lugar para interceptar a Claude Code **no es la red**: es el
propio Claude Code.

**Hooks.** Claude Code ejecuta hooks en eventos del ciclo de vida y varios pueden **bloquear**:

- `UserPromptSubmit` corre **antes de que el modelo vea el prompt** y puede abortarlo.
- `PreToolUse` corre antes de ejecutar una herramienta y puede denegarla con
  `permissionDecision: "deny"` y un `permissionDecisionReason`.
- Un hook bloquea con *exit code 2* (su stderr se muestra al usuario como motivo) o con exit 0 y un
  JSON de decisión.

Esto nos da, sin drivers ni certificados: el texto en claro, el archivo que se está adjuntando, el
comando que se va a correr — y **un canal de vuelta para explicarle al usuario por qué se bloqueó**,
que es el mejor lugar posible para la intervención pedagógica dentro de esa herramienta. Con
*managed settings* (política gestionada por la empresa) el empleado no puede desactivarlo. Pero es
un complemento del proxy, no un sustituto: cubre una herramienta, no la máquina.

**Gateway.** La otra vía para Claude Code es `ANTHROPIC_BASE_URL`: apuntar el CLI a un endpoint
propio compatible con la API de Anthropic, que inspecciona, decide y reenvía. Ve el request completo
(system prompt, adjuntos, resultados de herramientas). Más cobertura que los hooks, más trabajo, y
hay que manejar credenciales.

**Codex** no expone hoy un mecanismo de hooks equivalente y documentado, así que se cubre por la
capa C: honra `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` y confía CAs propias vía
`CODEX_CA_CERTIFICATE` (con `SSL_CERT_FILE` como fallback).

> **Insight para el pitch:** que Anthropic y OpenAI documenten oficialmente cómo confiar en la CA de
> un proxy corporativo significa que **el caso de uso de Aegis está soportado por diseño**, no es un
> hack que se rompe en la próxima versión.

### B. Extensión de navegador

Cubre ChatGPT, Gemini, Claude web y el largo tail de webs con IA. Ventaja sobre el proxy: ve el
contenido **antes** de que se cifre y puede intervenir en la interacción humana (pegar un bloque de
texto, arrastrar un archivo) mostrando el aviso en la propia página. Manifest V3 permite bloqueo
declarativo (`declarativeNetRequest`) y un content script para la capa de UI. Se despliega sin
fricción con force-install por política de Chrome/Edge Enterprise.

Limitación: no ve nada fuera del navegador, y no cubre navegadores que la empresa no gestione.

### C. Proxy MITM local con CA propia — el núcleo del MVP

Un proceso local (`127.0.0.1:8888`) que termina el TLS, inspecciona y reenvía. Lo que hay que
resolver:

**1. La CA.** El instalador genera una CA única por equipo (nunca se distribuye una clave común) y
la instala en los almacenes de confianza:

| SO | Comando |
|---|---|
| Windows | `certutil -addstore -user Root aegis-ca.crt` |
| macOS | `security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain aegis-ca.crt` |
| Linux | copiar a `/usr/local/share/ca-certificates/` + `update-ca-certificates` |
| **Firefox (cualquier SO)** | almacén propio NSS: `certutil -A -d sql:<perfil>` |

Firefox es la trampa clásica: no usa el almacén del sistema. `mkcert` es la referencia de cómo hacer
las cuatro cosas bien.

**2. Que las apps pasen por ahí.** Dos mundos distintos:

- *Apps que leen el proxy del sistema* (Chrome, Edge, Electron): Windows `netsh winhttp set proxy`
  más los Internet Settings de WinINET; macOS `networksetup -setsecurewebproxy`.
- *Apps que solo leen variables de entorno* (todo lo que sea Node, Go, Python, Rust — es decir,
  **todos los CLIs de IA**): el instalador debe fijar variables a nivel de usuario:

```
HTTPS_PROXY / HTTP_PROXY   → a dónde mandar el tráfico
NO_PROXY                   → allowlist de passthrough (banca, salud, updates del SO)
NODE_EXTRA_CA_CERTS        → Claude Code y cualquier app Node
CLAUDE_CODE_CERT_STORE     → qué almacenes confía Claude Code (default: bundled,system)
CODEX_CA_CERTIFICATE       → Codex CLI
SSL_CERT_FILE / REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE / GIT_SSL_CAINFO → Python, curl, git
```

Dos detalles no obvios: **Claude Code no soporta proxies SOCKS**, solo HTTP/HTTPS; y si el runtime
puede leer el almacén del SO (instalador nativo, o Node ≥ 22.15), basta con instalar la CA en el
sistema y ni siquiera hace falta `NODE_EXTRA_CA_CERTS`.

### D. Redirección forzada a nivel de SO — la versión enterprise

Para las apps que ignoran deliberadamente el proxy (o que se configuran solas), la única salida es
capturar la conexión antes de que salga del equipo:

- **Windows:** callout driver de WFP con *connect redirection* en la capa ALE — la conexión se
  redirige a nuestro proxy en localhost y el destino original se recupera desde los metadatos de
  WFP. Alternativa en user-mode: **WinDivert** (trae driver firmado, mucho más rápido de integrar,
  pero es fácilmente detectable y a veces lo marcan los antivirus).
- **macOS:** `NETransparentProxyProvider` (System Extension, macOS 11+). Es exactamente la API con
  la que están construidos los agentes DLP comerciales de macOS. Requiere entitlement de Apple.
- **Linux:** `nftables` / `iptables REDIRECT` + `SO_ORIGINAL_DST`, o un programa eBPF en
  `cgroup/connect4`.

### E. Sensor de conexiones por proceso — descubrimiento barato y total

Sin romper nada de TLS se puede saber **qué proceso habló con qué dominio**:

- **Windows:** `GetExtendedTcpTable` (PID ↔ IP remota) o, mejor, ETW con los proveedores
  `Microsoft-Windows-Kernel-Network` y `Microsoft-Windows-DNS-Client`, para correlacionar
  resolución DNS ↔ conexión ↔ proceso.
- **macOS:** `nettop` / `NEFilterDataProvider`. **Linux:** eBPF o `ss -tp`.

Esto es lo que alimenta el inventario de shadow AI: "el equipo de marketing abrió 14 dominios con IA
que no están en la lista aprobada". No ve el prompt, pero responde la pregunta del negocio y cuesta
un día de trabajo, no una semana.

---

## 4. Los seis obstáculos que van a aparecer (y qué hacer con cada uno)

1. **Certificate pinning.** Las apps que solo aceptan su propio certificado fallan con el MITM. La
   práctica estándar es una lista de *passthrough* por dominio. La buena noticia: los CLIs de IA que
   nos importan **no pinean** — al contrario, documentan cómo confiar en una CA corporativa.
2. **QUIC / HTTP3.** Chrome habla QUIC (UDP 443) con Google, así que Gemini se escaparía de un proxy
   TCP. La solución de toda la industria (Zscaler, Netskope, Cato, Palo Alto) es **bloquear UDP/443**
   para forzar el fallback a TCP; en entornos gestionados además se apaga con la política
   `QuicAllowed=false` de Chrome. Hay que documentarlo como decisión consciente, no descubrirlo en
   la demo.
3. **ECH (Encrypted Client Hello).** Cifra el SNI y mata la visibilidad de Nivel 1 desde la red. Es
   el argumento definitivo de por qué Aegis vive en el endpoint y no en un firewall.
4. **Apps que ignoran el proxy del sistema.** Cubiertas por variables de entorno hoy, por la capa D
   mañana. Lo importante es **detectar el hueco**: si el sensor (E) ve una conexión a un dominio de
   IA que el proxy nunca vio, eso es una alerta de evasión, no un silencio.
5. **Firefox y su almacén NSS propio.** Resuelto en el instalador.
6. **Permisos.** Instalar una CA en el almacén raíz y fijar el proxy del sistema requiere
   consentimiento explícito (y admin en algunos casos). Es un requisito, no un bug: sin
   consentimiento del dueño del equipo, esto no debería poder instalarse.

---

## 5. Cobertura real por herramienta objetivo

| Herramienta | Mejor capa | ¿Vemos el prompt? | Notas |
|---|---|---|---|
| **Claude Code** | A (hooks) + C | Sí | Bloqueo nativo con mensaje al usuario. Cero fricción. |
| **Codex CLI** | C | Sí | `HTTPS_PROXY` + `CODEX_CA_CERTIFICATE`. Documentado oficialmente. |
| **ChatGPT / Gemini / Claude web** | B o C | Sí | Con C hay que neutralizar QUIC para que Gemini no se escape. |
| **Claude Desktop / apps Electron** | C | Sí | Electron respeta el proxy del sistema. |
| **Cursor, Copilot, IDEs** | C | Sí | Respetan proxy y variables de entorno. |
| **Shadow AI desconocida** | E → clasificador | No (solo destino) | Es justamente el flujo que alimenta la lista negra. |

---

## 6. Arquitectura recomendada para el MVP

```
                        ┌─────────────────────────────────────────┐
   Claude Code ──hook──▶│                                         │
   Codex ─────env vars─▶│           AEGIS AGENT (local)           │
   Navegador ──proxy───▶│  proxy MITM local + CA propia + sensor  │
   Otras apps ─proxy───▶│                                         │
                        └────────────────┬────────────────────────┘
                                         │  decisión en <300ms
                     ┌───────────────────┴───────────────────┐
                     ▼                                       ▼
         ¿A DÓNDE va?  (destino)                   ¿QUÉ lleva?  (contenido)
         cache local → BD colaborativa             1. detectores deterministas
         → si el dominio es nuevo: clasificar         (regex de secretos, entropía, PII)
           UNA sola vez con LLM y compartir        2. solo si es ambiguo → LLM juez
           el veredicto entre todos los tenants
                     └───────────────────┬───────────────────┘
                                         ▼
                       permitir · redactar · bloquear + LECCIÓN
                                         │
                                         ▼
                         incidente → panel de la empresa (privado)
```

Dos principios que sostienen esto:

- **Lo colaborativo es solo el veredicto de un dominio**, nunca el contenido. Un dominio se
  investiga una vez en toda la red de clientes y el resultado se reparte. Los incidentes son
  privados por empresa. Es lo que hace que la lista negra crezca sola sin comprometer datos de
  nadie.
- **El LLM va al final, no al principio.** Estamos en el camino crítico de cada request: primero
  detectores deterministas (sub-milisegundo, auditables, sin falsos negativos en secretos con
  formato conocido), y el modelo solo para lo ambiguo y para clasificar dominios nuevos — que
  además se cachea para siempre.

### Qué construir, en orden

1. **Aegis Agent** — proxy MITM local, generación e instalación de la CA, instalador de un comando.
   Es la cobertura: sin esto no hay producto.
2. **Clasificador de destinos** + base de datos central compartida con cache.
3. **Detector de contenido** en cascada (ver [Investigación 02](02-motor-de-deteccion.md)).
4. **Panel** de empresa y de empleado con incidentes, patrones y lecciones.
5. **Sensor de conexiones** (Windows primero) para el inventario de shadow AI y para detectar el
   tráfico que se escapó del proxy.
6. **Hook de Claude Code** — opcional, si sobra tiempo: hace la demo más vistosa porque el bloqueo
   y la lección se ven dentro del propio CLI, pero no agrega cobertura.

### Qué NO hacer en el hackathon

- Escribir un driver de WFP o un System Extension de macOS. Se diseña, se presenta como roadmap y se
  demuestra que entendemos por qué existe.
- Intentar interceptar QUIC. Se bloquea y se documenta.
- Interceptar todo el tráfico del equipo sin filtro: el `NO_PROXY` con banca, salud y sistemas del
  SO no es opcional. Un DLP que lee el home banking del empleado es un incidente de seguridad, no un
  producto.

---

## 7. Consideración legal y ética

Aegis inspecciona tráfico de personas. Eso obliga a tres cosas desde el primer commit: consentimiento
explícito en la instalación, alcance limitado a dispositivos corporativos, y *passthrough* obligatorio
para categorías sensibles. El enfoque pedagógico del producto ayuda también acá: la narrativa no es
vigilancia, es formación — y eso cambia cómo lo recibe el empleado.

---

## Fuentes

- [Claude Code — Enterprise network configuration](https://code.claude.com/docs/en/network-config)
- [Claude Code — Hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code — Run Claude Code through a gateway](https://code.claude.com/docs/en/gateways)
- [Codex CLI behind TLS-inspecting proxies](https://codex.danielvaughan.com/2026/05/08/codex-cli-tls-inspecting-proxies-custom-ca-certificates-enterprise/)
- [Codex CLI proxy configuration: SOCKS, HTTP, and corporate networks](https://codex.danielvaughan.com/2026/04/18/codex-cli-proxy-configuration-socks-http-corporate-networks/)
- [mitmproxy — Certificates](https://docs.mitmproxy.org/stable/concepts/certificates/) · [Ignoring domains](https://docs.mitmproxy.org/stable/howto/ignore-domains/)
- [Microsoft Learn — Using Bind or Connect Redirection (WFP)](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/using-bind-or-connect-redirection)
- [WinDivert 2.2 documentation](https://reqrypt.org/windivert-doc.html)
- [Apriorit — Controlling and monitoring a network with user mode and driver mode techniques](https://www.apriorit.com/dev-blog/688-driver-controlling-and-monitoring-networks-with-user-mode-and-driver-mode-techniques)
- [Apple — NETransparentProxyProvider](https://developer.apple.com/documentation/NetworkExtension/NETransparentProxyProvider)
- [Zscaler — QUIC and the future of enterprise security](https://www.zscaler.com/blogs/product-insights/quic-secure-communication-protocol-shaping-future-of-internet)
- [Jimber — Encrypted traffic inspection 2026: TLS 1.3, QUIC & SASE](https://jimber.io/blog/encrypted-traffic-inspection-tls-13-quic-sase/)
- [Google — Use Chrome Enterprise Premium to integrate DLP with Chrome](https://support.google.com/chrome/a/answer/10104358)
- [CSA — AI browser extension security gaps (2026)](https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-browser-extension-security-gaps-2026041/)
- [Microsoft Presidio — PII detection guide](https://explainx.ai/blog/microsoft-presidio-pii-detection-anonymization-guide-2026)
