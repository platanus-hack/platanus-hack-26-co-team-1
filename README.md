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
agent/          Agente local: proxy de intercepción y motor de detección
  aegis_agent/detect/   Motor T1 (reglas deterministas) + redacción
  tests/                Tests del motor, incluidos los invariantes del contrato
  bench/                Medición de latencia en el camino crítico
docs/
  00-propuesta.md       El producto: problema, propuesta y requisitos del MVP
  adr/                  Decisiones de arquitectura y por qué se tomaron
  spec/                 Contrato de datos entre el agente y el backend
```

Las investigaciones que sustentan estas decisiones viven **fuera del repo**, en
`../investigacion/`: son notas de trabajo, no parte del producto.

## Decisiones tomadas

| ADR | Decisión |
|---|---|
| [0001](docs/adr/0001-interceptar-en-el-endpoint-por-capas.md) | Interceptar en el endpoint, por capas — la red ya no ve lo suficiente (TLS 1.3, ECH, QUIC) |
| [0002](docs/adr/0002-el-proxy-es-el-producto.md) | El proxy es el producto; las integraciones por aplicación son opcionales |
| [0003](docs/adr/0003-frontera-de-datos-local-decide-remoto-ensena.md) | Lo local decide, lo remoto enseña: el contenido interceptado nunca sale del equipo |

## Desarrollo

Requiere Python 3.11 o superior. El motor de detección no tiene dependencias externas.

```bash
cd agent
python -m unittest discover -s tests -t .   # tests
python -m bench.latency                     # latencia del motor T1
```

## Contexto

Proyecto para **Platanus Hack 26 — Bogotá** (21–23 agosto 2026), track de AI Security.
