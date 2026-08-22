# Aegis

**DLP conversacional con enfoque pedagógico para el uso seguro de IA en la empresa.**

Aegis se interpone entre el empleado y los agentes de IA (Claude Code, Codex, ChatGPT, Gemini y el
largo tail de *shadow AI*) para evitar que información privada — credenciales, datos de clientes,
código no público — salga de la organización. Su diferenciador no es solo bloquear: es entender
**por qué** la persona lo intentó y cerrar esa brecha de comprensión en el momento del incidente.

## Cómo funciona

La intercepción vive en el equipo del empleado, no en la red, y captura por **destino** — no por
aplicación. El mismo motor cubre un CLI, un navegador, un IDE o una app de escritorio que nadie
sabe que está instalada.

```
        ┌──────────────────── EQUIPO DEL EMPLEADO ────────────────────┐
        │                                                             │
  apps ─┼─▶ proxy local (CA propia) ─▶ ¿destino es IA? ─▶ detección ──┼─▶ permitir
        │                                    │              T1 reglas │    redactar
        │                                    │              T2 modelo │    bloquear
        └────────────────────────────────────┼─────────────────────────┘
                                             │  solo eventos redactados
                                             ▼
                          backend: clasificar dominios · panel · lección
```

La decisión de bloquear es **100% local**: sin red, Aegis sigue protegiendo. Lo único que cruza a
la nube son eventos ya redactados, según el [contrato de datos](docs/spec/contrato-de-datos.md).

## Estructura

```
agent/
  aegis_agent/
    detect/       Motor T1: reglas deterministas, normalización y redacción
    proxy/        Addon de mitmproxy: clasifica, decide, bloquea y explica
    panel/        Panel de la empresa: métricas sobre eventos redactados
    catalog.py    Catálogo semilla de servicios de IA (112 dominios)
    policy.py     Política, clasificación de destinos y detección por forma
    lessons.py    Lecciones locales de respaldo
  tests/          132 tests: reglas, evasión, shadow AI, datos, panel, base
                  colaborativa, instalador y end-to-end con navegador
    install/      Instalador reversible: CA, proxy del sistema y variables
    domains.py    Cliente de la base colaborativa, fuera del camino crítico
  bench/          Medición de latencia en el camino crítico
  demo/           Demo manual con navegador
backend/
  aegis_backend/  Base colaborativa: un dominio se clasifica una vez para todos
backend/
  aegis_backend/  Base colaborativa: un dominio se clasifica una vez para todos
api/              El panel como función serverless
docs/             Documentación técnica y de relevo (empezar por ESTADO.md)
```

**¿Retomando el proyecto?** Empezá por [`docs/ESTADO.md`](docs/ESTADO.md).

Las investigaciones que sustentan estas decisiones viven **fuera del repo**, en
`../investigacion/`: son notas de trabajo, no parte del producto.

## Decisiones tomadas

| ADR | Decisión |
|---|---|
| [0001](docs/adr/0001-interceptar-en-el-endpoint-por-capas.md) | Interceptar en el endpoint, por capas — la red ya no ve lo suficiente (TLS 1.3, ECH, QUIC) |
| [0002](docs/adr/0002-el-proxy-es-el-producto.md) | El proxy es el producto; las integraciones por aplicación son opcionales |
| [0003](docs/adr/0003-frontera-de-datos-local-decide-remoto-ensena.md) | Lo local decide, lo remoto enseña: el contenido interceptado nunca sale del equipo |

## Dos modos, y la empresa elige

| Modo | Qué hace con una IA no aprobada |
|---|---|
| `equilibrado` (por defecto) | La deja usar y analiza cada envío. El sitio abre normal, el trabajo fluye, y lo que no sale es el dato sensible. El uso queda registrado igual, así que el panel sigue mostrando el shadow AI. |
| `estricto` | Corta el destino. Nadie usa lo que no está aprobado. |

```bash
AEGIS_MODO=estricto      # o equilibrado
```

El equilibrado es el que sostiene una empresa real: bloquear la herramienta que
la gente ya usa termina en excepciones, VPNs y teléfonos personales, que es
exactamente donde nadie ve nada.

## Qué detecta

No solo credenciales. Tres familias, veinte reglas y una señal de volumen:

| Familia | Ejemplos |
|---|---|
| **Credenciales** | Llaves de AWS, Anthropic, OpenAI, GitHub, Google, Slack, Stripe; llaves privadas, JWT, cadenas de conexión |
| **Datos de la empresa** | Volcados de base de datos, filas con datos reales, esquemas con columnas de salarios, exports de clientes en CSV, documentos marcados como internos |
| **Datos personales** | Tarjetas con Luhn, cédulas y documentos latinoamericanos, IBAN, correos |

La señal de volumen es la que ninguna regla individual puede dar: un correo en un prompt es una
mención, quince en el mismo envío son una base de clientes.

Y resiste los caminos por los que un dato se escapa sin que nadie lo intente: base64 simple y doble,
gzip, `.docx`, UTF-16, percent-encoding, escapes de JSON, texto partido con espacios y secretos
escondidos al final de un archivo grande.

## Desarrollo

Requiere Python 3.11 o superior. El motor de detección no tiene dependencias externas.

```bash
cd agent
python -m pip install -r requirements.txt   # mitmproxy y playwright
python -m playwright install chromium

python -m unittest discover -s tests -t .   # los 132 tests (o: python ../run_tests.py)
python -m bench.latency                     # latencia del motor T1
python -m demo.run                          # demo con navegador
python -m aegis_agent.panel.server          # panel en :8787
python -m aegis_backend.app                 # base colaborativa en :8686 (desde backend/)
```

Para usarlo con tu propio navegador en vez del de la demo:

```bash
python -m aegis_agent.install.windows plan        # qué va a hacer, antes de hacerlo
python -m aegis_agent.install.windows install     # CA + proxy + variables (solo tu usuario)
python -m aegis_agent.install.windows uninstall   # revierte todo
```

Medido en un portátil, sin GPU: un prompt típico se inspecciona en **0.16 ms**, y un archivo de
44.000 caracteres en 29 ms. La decisión de bloquear no hace una sola llamada de red.

## Panel desplegado

https://aegis-theta-eight.vercel.app — el mismo código de métricas y render que
corre local. Con `AEGIS_EVENTS_URL` apuntando ahí, el agente sube sus eventos
redactados en segundo plano y el panel los muestra en vivo.

## Contexto

Proyecto para **Platanus Hack 26 — Bogotá** (21–23 agosto 2026), track de AI Security.
