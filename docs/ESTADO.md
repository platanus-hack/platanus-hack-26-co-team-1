# Estado del proyecto — relevo

> Este documento es el punto de entrada si vas a retomar Aegis sin haber estado
> antes. Léelo completo antes de tocar código: buena parte de lo que parece una
> decisión arbitraria está justificada por una medición o por un bug que ya
> encontramos.

**Última actualización:** 22 de agosto de 2026
**Estado:** MVP funcionando de punta a punta, verificado en una máquina real.
**Tests:** 425 en verde (`python run_tests.py` desde la raíz).
**Entorno:** `agent/requirements.txt` para el proxy y los tests;
`agent/requirements-modelo.txt` para T2, que va aparte porque es opcional y pesa.

---

## 1. Qué es Aegis en una frase

Un proxy local que se interpone entre el empleado y los servicios de IA, decide
**en el equipo** si lo que se está enviando contiene información que no debe
salir, y convierte cada bloqueo en una lección para esa persona.

## 2. Qué funciona hoy

| Pieza | Estado | Dónde |
|---|---|---|
| Motor T1: 28 reglas deterministas + firmas de archivo | Funciona | `agent/aegis_agent/detect/` |
| Motor T2: modelo local (GLiNER) | Funciona, **apagado por defecto**. Etiquetas y umbral elegidos midiendo | `agent/aegis_agent/detect/model.py` |
| Sensor de puntos ciegos (capa D) | Funciona | `agent/aegis_agent/sensor.py` |
| Corte del punto ciego por firewall | Funciona, requiere administrador | `agent/aegis_agent/install/firewall.py` |
| Política como dato, editable desde el backend | Funciona | `agent/aegis_agent/policy_store.py` |
| Verificación de cobertura de escritorio | Funciona | `install/windows.py verificar` |
| Normalización anti-evasión (base64, gzip, docx, UTF-16…) | Funciona | `agent/aegis_agent/detect/payload.py` |
| Proxy de intercepción (mitmproxy) | Funciona | `agent/aegis_agent/proxy/` |
| Catálogo de 167 dominios de IA + 7 patrones regionales | Funciona | `agent/aegis_agent/catalog.py` |
| Detección de shadow AI por comportamiento | Funciona | `agent/aegis_agent/signals.py` |
| Base colaborativa de dominios + clasificador | Funciona | `backend/aegis_backend/` |
| Panel de la empresa | Funciona, desplegado | `agent/aegis_agent/panel/`, `web/app.py` |
| Instalador para Windows (CA + proxy + variables) | Funciona | `agent/aegis_agent/install/windows.py` |
| Cobertura de **Claude Code** | Verificada con el CLI real | ver §8 |
| Cobertura de **Codex** | Mecanismo listo, **sin verificar** | ver §8 |
| Lecciones pedagógicas | **Las genera un modelo** desde el evento redactado | `backend/aegis_backend/lecciones.py` |
| Inyección de prompts, en las dos direcciones | Funciona, avisa por defecto | `agent/aegis_agent/detect/inyeccion.py` |
| Diccionario de la empresa (sus clientes, proyectos, dominios) | Funciona | `agent/aegis_agent/detect/diccionario.py` |
| Sistema de diseño único en las tres superficies | Funciona | `agent/aegis_agent/ui/tokens.py` |
| Atribución por aplicación y política por app | Funciona | `agent/aegis_agent/procesos.py`, [ADR 0004](adr/0004-la-politica-conoce-la-aplicacion-el-detector-no.md) |
| Subida de archivos hacia una IA | Funciona (navegador). Falta la app de escritorio | `agent/aegis_agent/subidas.py` |
| Filtro de placeholder + validadores de contexto | Funciona | `agent/aegis_agent/detect/placeholders.py`, `contexto.py` |
| Banco de precisión + trinquete en la suite | Funciona, 1.375 casos | `agent/bench/precision.py` |

**Desplegado:** https://aegis-panel.onrender.com — un solo servicio con el front y el API

## 3. Qué NO existe todavía

Por orden de lo que más falta para el pitch:

1. **El clasificador de dominios sigue siendo heurístico.** Las lecciones ya las
   genera un modelo (`backend/aegis_backend/lecciones.py`); el clasificador tiene
   el camino escrito y probado con un modelo simulado, y espera la misma API key.
   La clave vive fuera del repositorio: ver `backend/aegis_backend/secretos.py`.
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
| Las etiquetas del modelo se eligen midiendo, no por intuición: `empresa` encontraba 13/25 pero bloqueaba 6/36 frases de trabajo normal. | `bench/evaluar_modelo.py` |
| **"contraseña" con eñe no la veía ninguna regla.** Las reglas y el corpus estaban escritos sin tildes, así que la cobertura se veía perfecta y la palabra más importante del idioma para este producto pasaba de largo. No era una evasión: era la ortografía. | `test_credenciales_en_lenguaje_natural.py` |
| El escape del JSON fabrica credenciales: "explícitamente" viaja como `explícitamente`, y esos dígitos vuelven una palabra corriente indistinguible de una contraseña. Cerca de "usuario" bloqueó una sesión entera de Claude Code por su propio archivo de memoria. | `test_credenciales_en_lenguaje_natural.py` |
| Importar `proxy/addon.py` levantaba un agente de verdad (`addons = [Aegis()]` al final del módulo): la suite le escribía `~/.aegis/politica.json` al desarrollador. | `test_politica.py` |
| `AEGIS_MODO` dejó de existir cuando la política pasó a vivir en disco: el archivo mandaba siempre. | `test_politica.py` |
| Todos los eventos decían `process: "browser"`, incluso los de un CLI. El contrato pedía ese campo desde el primer día. | `test_atribucion_por_proceso.py` |
| Una política **parcial** reseteaba en silencio todo lo que no nombraba: un backend con código anterior le devolvió el bloqueo a un equipo que estaba en modo observación. Ahora se mezcla sobre la que había. | `test_atribucion_por_proceso.py` |
| El proxy escuchaba en todas las interfaces: un proxy que descifra TLS abierto al wifi de al lado. Ahora va atado a loopback. | — |
| Con Aegis en el medio, **Claude Code no podia ni autenticarse**: su propio token hacia api.anthropic.com se leia como una fuga. Una credencial que va hacia su dueño no es una fuga. | `test_dueno_de_la_credencial.py` |
| La regla genérica disparaba sobre marcado: un `` `git ... `` en el contexto bloqueaba una sesión limpia. | `test_dueno_de_la_credencial.py` |
| **`sk-proj-XXXXXXXX` y `postgres://user:password@localhost` cortaban el envío.** Un placeholder tiene forma de credencial y no es ninguna, y las reglas de *formato* no tenían validador porque el formato les alcanzaba. Un desarrollador preguntando por su propio `.env.example` se comía un 403. El filtro va en el motor, no en cada regla, para que ninguna regla nueva se olvide de pasarlo. Y **no** filtra por la palabra "example": la llave canónica de AWS es `AKIAIOSFODNN7EXAMPLE`, así que eso sería el bypass más fácil del producto. | `test_placeholders.py` |
| **El adjunto se iba sin abrirse.** Los bytes de un archivo arrastrado a ChatGPT van a `files.oaiusercontent.com`, no a `chatgpt.com`, y `looks_like_ai_api` busca la forma de una *conversación*: una subida no la tiene. No era una regla que faltaba, era un agujero en el embudo. | `test_subida_de_archivos.py` |
| **`c.c. 43.115.902` no se veía nunca** — la forma más común de escribir una cédula en Colombia. El `` iba después de toda la alternancia y `c.c.` termina en punto: un límite de palabra pegado a un punto necesita un carácter de palabra al lado. A ojo la alternancia se ve perfecta; lo encontró el banco de precisión. La CURP tenía el mismo error, tres líneas más arriba, ya arreglado para la cédula. | `test_trinquete_precision.py` |
| **`la password del servidor de producción es X` se iba entera.** Las dos reglas de credencial en español tenían listas de anclas **distintas** y se habían ido separando. Y `Sup3rS3cret1` da 3,08 bits de entropía —por debajo del umbral— siendo exactamente la clave que una política de empresa obliga a poner: la condición de mezcla de clases vivía dentro de una sola regex y ahora es una función que las dos comparten. | `test_trinquete_precision.py` |

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
2. **Conectar el front con la política.** La cañería ya está de los dos lados:
   `Policy.a_dict()`, `policy_store`, `PUT /v1/policy/{tenant}`, y en la rama
   `feature/frontend-ui` la pantalla de Políticas con sus tabs. Lo que falta es
   que el formulario escriba de verdad — hoy es todo estado local del componente.
   El diccionario de la empresa es el campo que más rinde conectar primero.
3. **Más casos de negocio en el corpus.** El corpus ya no son 84 frases: son
   1.375, y hay un banco que mide la precisión del corte con un trinquete en la
   suite (`bench/precision.py`, [§9](#9-la-precisión-medida)). Lo que sigue
   faltando es lo mismo de antes y es lo único que falta: **casos de negocio
   reales**. Las 1.291 frases nuevas son generadas por composición, y para las
   que tienen formato eso mide regresión y no cobertura. La receta buena es
   generación sintética con un LLM sobre plantillas de dominio (es lo que hace el
   paper de CAPID) y está bloqueada por la misma API key del punto 1. El otro
   camino, gratis y disponible hoy, es bajar el split en español de
   `ai4privacy/pii-masking-400k`.
4. **Un disco en Render** (o un KV) para que el panel desplegado no pierda los
   eventos: el código ya persiste en disco si `AEGIS_DATA_DIR` apunta a uno, pero
   el plan gratuito no monta discos y hoy degrada a memoria.
5. **Instalador de macOS**, si hay alguien del equipo en Mac.

## 8. Cobertura de los CLI de IA

**Claude Code: verificado con el binario real**, no con una simulación.

```
claude -p "Responde solo con la palabra LISTO"          -> LISTO
claude -p "Revisa: AWS_ACCESS_KEY_ID=AKIAIOSF..."       -> 403, con la lección
                                                            dentro del propio CLI
```

Funciona porque Claude Code lee `HTTPS_PROXY` y `NODE_EXTRA_CA_CERTS`, que el
instalador deja puestas. La lección viaja en el `error.message` del 403, así que
la persona la ve sin salir de la terminal.

**Codex: sin verificar.** No está instalado en la máquina de desarrollo. El
mecanismo es el mismo y las variables ya están puestas (`CODEX_CA_CERTIFICATE`,
`SSL_CERT_FILE`, `HTTPS_PROXY`), y la documentación de OpenAI dice que el CLI las
honra, pero **eso no es lo mismo que haberlo probado**. Si instalás Codex, la
prueba es idéntica a la de arriba y toma dos minutos.

## 9. La precisión medida

Antes de este banco, la precisión de T1 no tenía número: se sabía que las reglas
funcionaban porque había tests, que es otra cosa. El banco corre sobre 1.375
casos y reporta tres cifras:

```bash
cd agent
python -m bench.precision              # el reporte
python -m bench.precision --guardar    # y subir la línea base
```

| Métrica | Hoy |
|---|---|
| **Precisión del corte** (de lo que Aegis frena, cuánto merecía frenarse) | **100 %** |
| Falsos positivos que **cortan**, sobre 524 negativos duros | **0** |
| Falsos positivos que solo avisan | **0** |
| Recall: secretos con formato / credenciales en español / documentos / exports | 280/280 · 256/256 · 77/77 · 16/16 |

**El número es la precisión del corte y no el F1**, por una razón asimétrica: un
aviso equivocado cuesta atención, un corte equivocado cuesta el producto. Quien
recibe un bloqueo injustificado no abre un ticket, busca cómo desinstalar Aegis,
y a partir de ahí el recall real es cero.

**Y hay que saber leerlo.** Los positivos con formato los fabrica el mismo prefijo
que busca la regla: ahí la medición es de **regresión**, no de cobertura. Donde sí
hay evidencia es en los 524 negativos duros, que ninguna regla vio nunca cuando
se escribió. Está explicado en `bench/corpus_generado.py` y conviene leerlo antes
de citar el 100 % en una presentación.

El trinquete (`tests/test_trinquete_precision.py`) corre con la suite y se pone
rojo si baja la precisión, si suben los falsos positivos, si baja el recall de
alguna familia, o si el corpus se encogió. Se verificó que muerde: quitando una
regla el recall cae a 214/256, y agregando una regla ruidosa la precisión cae a
99,10 %.

## 10. Documentos

- [Arquitectura](ARQUITECTURA.md) — cómo encaja todo y por dónde pasa un request
- [Operación](OPERACION.md) — cómo levantar cada pieza y todas las variables
- [Modelo local](MODELO-LOCAL.md) — T2: instalación, etiquetas, métricas, cómo refinarlo
- [Propuesta](00-propuesta.md) — el producto: problema, propuesta y requisitos del MVP
- [ADR](adr/) — las decisiones y por qué se tomaron
- [Contrato de datos](spec/contrato-de-datos.md) — qué cruza la frontera

Las investigaciones que sustentan las decisiones están **fuera del repo**, en
`../investigacion/`: intercepción de tráfico, motor de detección, competencia del
nicho y elección del modelo local.
