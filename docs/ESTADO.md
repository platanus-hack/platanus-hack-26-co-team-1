# Estado del proyecto — relevo

> Este documento es el punto de entrada si vas a retomar Aegis sin haber estado
> antes. Léelo completo antes de tocar código: buena parte de lo que parece una
> decisión arbitraria está justificada por una medición o por un bug que ya
> encontramos.

**Última actualización:** 22 de agosto de 2026
**Estado:** MVP funcionando de punta a punta, verificado en una máquina real.
**Tests:** 395 en verde (`.venv/Scripts/python run_tests.py` desde la raíz).
**Entorno:** hay un `.venv` en la raíz. Ver `agent/requirements.txt` y
`agent/requirements-modelo.txt` (T2 va aparte porque es opcional y pesa).

---

## 1. Qué es Aegis en una frase

Un proxy local que se interpone entre el empleado y los servicios de IA, decide
**en el equipo** si lo que se está enviando contiene información que no debe
salir, y convierte cada bloqueo en una lección para esa persona.

## 2. Qué funciona hoy

| Pieza | Estado | Dónde |
|---|---|---|
| Motor T1: 27 reglas deterministas + firmas de archivo | Funciona | `agent/aegis_agent/detect/` |
| Motor T2: modelo local (GLiNER) | Funciona, **apagado por defecto**. Etiquetas y umbral elegidos midiendo | `agent/aegis_agent/detect/model.py` |
| Sensor de puntos ciegos (capa D) | Funciona | `agent/aegis_agent/sensor.py` |
| Corte del punto ciego por firewall | Funciona, requiere administrador | `agent/aegis_agent/install/firewall.py` |
| Política como dato, editable desde el backend | Funciona | `agent/aegis_agent/policy_store.py` |
| Detección configurable por política: reglas apagadas, términos prohibidos, regex propias, perillas de T2 | Funciona | `agent/aegis_agent/detect/ruleset.py` |
| Hot-reload de la política: lo que la web guarda aplica en ~60s sin reiniciar | Funciona | `addon.py` `_refrescar_politica`, `AEGIS_REFRESCO_POLITICA` |
| Verificación de cobertura de escritorio | Funciona | `install/windows.py verificar` |
| Normalización anti-evasión (base64, gzip, docx, UTF-16…) | Funciona | `agent/aegis_agent/detect/payload.py` |
| Proxy de intercepción (mitmproxy) | Funciona | `agent/aegis_agent/proxy/` |
| Catálogo de 112 dominios de IA | Funciona | `agent/aegis_agent/catalog.py` |
| Detección de shadow AI por comportamiento | Funciona | `agent/aegis_agent/signals.py` |
| Base colaborativa de dominios + clasificador | Funciona | `backend/aegis_backend/` |
| Panel de la empresa | Funciona, desplegado | `agent/aegis_agent/panel/`, `api/index.py` |
| Instalador para Windows (CA + proxy + variables) | Funciona | `agent/aegis_agent/install/windows.py` |
| Lecciones pedagógicas | Locales, estáticas | `agent/aegis_agent/lessons.py` |

**Panel desplegado:** https://aegis-theta-eight.vercel.app

## 3. Qué NO existe todavía

Por orden de lo que más falta para el pitch:

1. **Las lecciones no las genera un modelo.** Están escritas a mano en
   `lessons.py`. El contrato de datos define `POST /v1/lessons` y el backend
   responde un placeholder. Falta conectar un LLM que las genere a partir del
   evento redactado. **Requiere `ANTHROPIC_API_KEY`, que no está configurada.**
2. **El clasificador de dominios tampoco usa un modelo.** Descarga la portada del
   sitio y decide con una heurística de contenido. El camino del modelo está
   escrito y probado con uno simulado; espera la misma API key.
3. **No hay perfil de empresa ni de empleado.** El panel es de un solo tenant.
   La política ya **no** vive en código: se lee de `~/.aegis/politica.json` y el
   backend la sirve por `GET`/`PUT /v1/policy/{tenant}`. Lo que falta es la
   pantalla que la edite y los dos roles.
4. **No hay instalador para macOS ni Linux.** Solo Windows.
5. **Las apps que ignoran el proxy del sistema no se pueden interceptar.** Es la
   capa D del ADR 0001. Lo que sí existe ahora: el sensor las detecta, y con
   `blind_spot_action = "block"` se les corta la ruta directa por firewall. Lo
   que no existe es *ver* qué mandaron: para eso haría falta un driver WFP.
6. **El almacenamiento del panel desplegado es efímero.** Sin `AEGIS_KV_URL` los
   eventos viven mientras la función esté caliente.

## 4. Las decisiones que no hay que deshacer sin leer

Están en `docs/adr/`. Las tres que más condicionan el código:

- **[ADR 0001](adr/0001-interceptar-en-el-endpoint-por-capas.md)** — se intercepta
  en el equipo, no en la red. TLS 1.3, ECH y QUIC dejaron ciega a la red.
- **[ADR 0002](adr/0002-el-proxy-es-el-producto.md)** — la cobertura la da el
  punto de intercepción, no la aplicación. El detector no sabe qué app originó el
  tráfico, y eso es a propósito.
- **[ADR 0003](adr/0003-frontera-de-datos-local-decide-remoto-ensena.md)** — la
  decisión es 100% local y el contenido nunca sale del equipo. Todo lo que sube
  es un evento redactado ([contrato](spec/contrato-de-datos.md)).

Y dos reglas de producto que están sostenidas por medición, no por gusto:

- **El destino filtra antes que el contenido.** Solo se inspecciona el payload de
  las conexiones que van a una IA. Correr contra tráfico real mostró que sin esto
  el agente escanea cada POST de la navegación y llena el panel de ruido.
- **Lo que ve el modelo bloquea según la categoría, no a ciegas.** T1 detecta
  con certeza y T2 con probabilidad: `secret` e `internal_data` cortan igual
  que si los hubiera visto T1, pero `pii` suelto solo advierte. Se baja todo a
  advertencia, sin mirar la categoría, con `AEGIS_T2_ACCION=warn`.

## 5. Bugs reales que ya encontramos (no los reintroduzcas)

Cada uno tiene su test; si tocás esa zona y el test se pone rojo, es esto:

| Qué pasaba | Dónde está el test |
|---|---|
| `copilot.microsoft.com` pasaba libre porque `microsoft.com` estaba en passthrough y esa lista se evaluaba primero. Ahora gana el dominio más específico. | `test_shadow_ai.py` |
| El secreto escondido al final de un archivo grande no se veía: la cola que se conservaba a propósito se recortaba otra vez al escanear. | `test_evasion.py` |
| Un adjunto binario rompía el decode de texto y se perdía el nombre del archivo. Los nombres se leen sobre los bytes crudos. | `test_archivos_criticos.py` |
| `AWS_SECRET_ACCESS_KEY=` no matcheaba: los guiones bajos son caracteres de palabra y el `\b` nunca casaba. | `test_proveedores.py` |
| El prompt viaja dentro de un JSON, así que `password = "..."` llega escapado y ninguna regla lo veía. | `test_proveedores.py` |
| Responder a un `fetch` con HTML deja la aplicación girando para siempre. Ahora se responde JSON si no es una navegación. | `test_respuesta_bloqueo.py` |
| Las etiquetas del modelo se eligen midiendo, no por intuicion: `empresa` encontraba 13/25 pero bloqueaba 6/36 frases de trabajo normal. | `bench/evaluar_modelo.py` |

## 6. Trampa de herramientas que te va a morder

Escribir archivos con `\b` dentro de una expresión regular a través de las
herramientas de edición puede grabar un carácter de retroceso literal
(`\x08`) en vez del límite de palabra. Pasó una vez y costó media hora de
depuración: la regex se veía bien y no matcheaba nada.

Para verificar:

```bash
python -c "
import pathlib
for f in list(pathlib.Path('agent').rglob('*.py')) + list(pathlib.Path('backend').rglob('*.py')):
    if bytes([8]) in f.read_bytes(): print('CORROMPIDO:', f)
"
```

Para reparar: leer los bytes y reemplazar `bytes([8])` por `bytes([92, 98])`.

## 7. Por dónde seguir

En el orden en que más valor agregan:

1. **Conectar el modelo a las lecciones y al clasificador de dominios.** Es lo
   único que separa el producto actual del que dice la propuesta. Solo falta la
   API key; el código y los tests con modelo simulado ya están.
2. **La pantalla que edita la política.** La cañería ya está: `Policy.a_dict()`,
   `policy_store` y `PUT /v1/policy/{tenant}`. Falta el formulario y los roles.
3. **Más casos de negocio en el corpus.** `bench/corpus.py` tiene 61 frases y
   con eso ya se eligieron etiquetas y umbral. Donde el modelo ve menos es en
   datos de la empresa (1/14): esas frases son las que más rinde agregar.
4. **Vercel KV** para que el panel desplegado no pierda los eventos.
5. **Instalador de macOS**, si hay alguien del equipo en Mac.

## 8. Documentos

- [Arquitectura](ARQUITECTURA.md) — cómo encaja todo y por dónde pasa un request
- [Operación](OPERACION.md) — cómo levantar cada pieza y todas las variables
- [Modelo local](MODELO-LOCAL.md) — T2: instalación, etiquetas, métricas, cómo refinarlo
- [Propuesta](00-propuesta.md) — el producto: problema, propuesta y requisitos del MVP
- [ADR](adr/) — las decisiones y por qué se tomaron
- [Contrato de datos](spec/contrato-de-datos.md) — qué cruza la frontera

Las investigaciones que sustentan las decisiones están **fuera del repo**, en
`../investigacion/`: intercepción de tráfico, motor de detección, competencia del
nicho y elección del modelo local.
