# El modelo local (nivel T2)

Todo lo que hace falta para instalarlo, entender qué hace, medirlo y refinarlo.

---

## 1. Qué es y qué no es

**Es** un extractor de entidades de **289M de parámetros** que corre en CPU:
[`urchade/gliner_multi-v2.1`](https://huggingface.co/urchade/gliner_multi-v2.1).

> Este documento decía ~50M y son 289M, casi seis veces más. El número no era una
> curiosidad: sostenía la afirmación de que el modelo es liviano, y esa afirmación
> es la que decide si esto se puede instalar en el equipo de cada empleado. Se
> midió contando parámetros, no leyendo la tarjeta del modelo.

**No es** un modelo de lenguaje. Un LLM local serían gigabytes de RAM y segundos
de latencia, y esto está en el camino crítico de cada envío. La confusión entre
"modelo local" y "LLM local" es la que hace que la gente descarte la idea antes
de mirarla.

Existe para lo que ninguna regla puede ver. T1 encuentra una llave de AWS porque
**tiene un formato**; no encuentra *"el cliente Bancolombia está renegociando el
contrato de nómina"* porque eso no tiene formato, tiene sentido.

## 2. Instalación

```bash
cd agent
python -m pip install gliner onnxruntime
```

El modelo se descarga solo la primera vez que se usa. Pesa **1.1 GB** y deja
**2.3 GB** en la caché de `huggingface_hub`, porque baja los pesos dos veces (en
`safetensors` y en `pytorch_model.bin`). La carga en frío son unos 9 segundos; la
segunda vez arranca directo.

**Está apagado por defecto.** Se prende con:

```bash
AEGIS_T2=1
```

Arrancar descargando un giga la primera vez que alguien abre un chat sería una
forma rara de presentarse, y el agente protege igual sin él.

## 3. Las etiquetas

El modelo recibe las etiquetas **como texto**, así que agregar un tipo de dato es
configuración de la empresa y no un release del producto.

Y tienen dos niveles de autoridad, que es la decisión central de este documento:

| Etiqueta | Categoría | Qué hace |
|---|---|---|
| `nombre de cliente` | internal_data | **corta el envío** |
| `empresa` | internal_data | avisa |
| `dinero` | internal_data | avisa |
| `credencial` | pii | avisa |
| `condicion de salud` | pii | avisa |
| `persona` | pii | avisa |
| `empleado` | pii | avisa |
| `domicilio` | pii | avisa |

**Avisar no le cuesta nada a la persona.** El envío sale igual, no ve ningún
cartel, no se frena su trabajo: el hallazgo solo queda registrado en el panel, y
de ahí salen las lecciones. Por eso una etiqueta que se equivoca seguido puede
avisar sin problema, pero no puede cortar.

La autoridad se decide **por etiqueta y no por categoría** (`model_block_labels`
en `Policy`), porque dos etiquetas del mismo tipo de dato miden muy distinto:
`empresa` y `nombre de cliente` son las dos `internal_data`, pero la primera se
equivoca en 6 de 36 frases normales y la segunda en 1.

**Cómo se eligieron, y qué hay que desaprender.** Se midió etiqueta por etiqueta
sobre el corpus de `bench/corpus.py` (25 frases sensibles, 36 de trabajo normal):

| Etiqueta | Encuentra | Ensucia | Veredicto |
|---|---|---|---|
| `empresa` / `organizacion` | 13/25 | **6/36** | descartadas: ruidosas |
| `nombre de cliente` | 9/25 | 1/36 | **elegida** |
| `persona` | 13/25 | 4/36 | elegida, pero solo advierte |
| `dinero` / `monto` | 5/25 | 3/36 | descartadas: ruidosas |
| `condicion de salud` | 5/25 | **0/36** | elegida |
| `domicilio` | 3/25 | **0/36** | elegida (mejor que `direccion`) |
| `contrasena` / `clave` | **0/25** | — | descartadas: no encuentran nada |
| `diagnostico medico` | **0/25** | — | descartada |

Dos cosas que este documento afirmaba y la medición corrigió:

1. **La etiqueta corta no siempre gana.** `nombre de cliente` es más precisa que
   `empresa`, y `condicion de salud` más limpia que `enfermedad`. Lo que importa
   no es el largo: es que la etiqueta nombre **la relación**, no la cosa. Un
   extractor de entidades no distingue mencionar de filtrar, y "empresa" marca
   *"explicame qué hace Bancolombia como negocio"* igual que marca un contrato.
2. **`contrasena` no encuentra contraseñas.** Cero sobre 25. Detecta la palabra,
   no el secreto: marca *"cómo genero una contraseña segura"* y no ve
   *"la contraseña del servidor es Verano2026Bogota"*. Ese caso lo cubre T1 con
   la regla `credencial_en_espanol`, que es determinista.

## 4. Métricas medidas

Con `bench/evaluar_modelo.py` sobre el corpus completo (25 frases sensibles, 36
de trabajo normal), en CPU sin GPU, dándole al modelo el prompt ya extraído:

| Umbral | Detecta | **Bloquea trabajo normal** | Avisa de más |
|---|---|---|---|
| 0.50 (actual) | 21/25 | **0**/36 | 13/36 |
| 0.60 | 21/25 | **0**/36 | 10/36 |

```
Latencia:  p50 88 ms | p95 99 ms | presupuesto 700 ms
Carga:     ~5 s, en un hilo al arrancar el proxy y no en el primer envío
```

Por grupo, en 0.5:

| Grupo | Resultado |
|---|---|
| Fugas de datos de empresa | 13/14 detectadas |
| Datos personales y de salud | 8/8 detectadas |
| Credenciales en lenguaje natural | 2/8 — **las ve T1**, 8/8, con dos reglas deterministas |
| Trabajo de rutina | 0/12 marcadas |
| Menciones de empresa sin fuga | 5/6 marcadas, **0 bloqueadas** |

**Lo que hay que saber para no sobrevender esto.** El modelo no distingue
mencionar de filtrar: marca *"explicame qué hace Bancolombia"* igual que marca un
contrato. Por eso lo que ve **avisa y no corta**, salvo la única etiqueta que
midió lo bastante bien. El bloqueo con autoridad sigue siendo trabajo de T1.

Dos mediciones anteriores de este documento quedan anuladas: estaban hechas sobre
17 frases y sobre el cuerpo crudo del request. Con el JSON completo el modelo
marcaba 8 de cada 10 frases normales, porque los nombres de parámetros le daban
entidades por todos lados.

## 5. Cómo medirlo vos

```bash
cd agent
AEGIS_T2=1 python -m bench.evaluar_modelo
AEGIS_T2=1 python -m bench.evaluar_modelo --umbrales 0.4,0.5,0.6,0.7
```

Reporta primero los **falsos positivos**, y es a propósito: el criterio de
aceptación más duro no es cuánto detecta sino cuánto NO detecta. Un T2 ruidoso es
peor que no tener T2, porque enseña a la gente a ignorar los avisos.

## 6. Las tres reglas que lo gobiernan

1. **Corre solo cuando T1 no encontró nada.** Si ya hay una credencial detectada,
   gastar 110 ms más no cambia la decisión ni la lección.
2. **Tiene un presupuesto de latencia duro.** Si tarda más de 700 ms se descarta
   su respuesta y queda lo de T1. Un modelo lento no puede frenar a la persona.
3. **Bloquea según la categoría, no a ciegas.** T1 detecta con certeza y el
   modelo con probabilidad, así que no toda categoría merece la misma
   autoridad: `secret` e `internal_data` cortan igual que si los hubiera visto
   T1, pero `pii` suelto (nombre, dirección) solo advierte, porque ahí el costo
   de un falso positivo es más alto que el de dejarlo pasar. `AEGIS_T2_ACCION=warn`
   es la salida de emergencia completa para la empresa que no confía nada en el
   modelo: con eso, ningún hallazgo del modelo bloquea, sin importar la categoría.

Y una cuarta, implícita: **si no está instalado, el agente funciona igual.** Hay
tests que verifican que el motor sigue detectando todo lo de T1 con el modelo
ausente, caído o lento.

## 7. Cómo refinarlo

Por orden de lo que más rinde:

**a. Corpus propio en español.** Es lo que más falta. Ampliá las dos listas de
`bench/evaluar_modelo.py` con frases reales del negocio (anonimizadas) y volvé a
medir los umbrales. El corpus actual son 61 frases en `bench/corpus.py`, y lo
que más rinde es agregar casos de negocio reales: ahí es donde el modelo hoy ve
menos.

**b. Etiquetas del negocio.** `AEGIS_T2_ETIQUETAS` no existe todavía, pero
`scan_model()` ya recibe las etiquetas como parámetro: exponerlo en la política de
la empresa es un cambio chico. Candidatas obvias: `numero de poliza`,
`numero de contrato`, `codigo de proyecto`.

**c. Un modelo más chico.** Ya está medido: ver la sección 9. `gliner_small-v2.1`
pesa la cuarta parte y no detecta menos. Se cambia con `AEGIS_T2_MODELO`.

**d. Exportar a ONNX cuantizado.** Bajaría el peso en disco y la RAM. Vale la
pena cuando haya que distribuirlo en un instalador; hoy `pip install` lo resuelve.

**e. Afinar el modelo.** Ver la sección 9: hoy la respuesta medida es **no**, y
hay una razón concreta, no un "todavía no". Antes de entrenar nada, medí.

## 8. Sobre distribuir los pesos

No publicamos los pesos en una release del repo. El modelo es de terceros, ya está
en Hugging Face y bajarlo desde ahí es una línea. Lo que sí es nuestro y vale la
pena versionar es **la configuración**: etiquetas, umbral, mapeo a categorías y el
arnés de evaluación, y todo eso está en el repo.

Si más adelante afinamos un modelo propio con corpus de la empresa, ahí sí tiene
sentido una release con los pesos, y el lugar natural es `AEGIS_T2_MODELO`
apuntando a una ruta local en vez de a un identificador de Hugging Face.

## 9. ¿Otro modelo? ¿Fine tuning? Las dos, medidas

Cuatro candidatos de la misma familia, el mismo corpus, la misma política:

```bash
cd agent
AEGIS_T2=1 python -m bench.comparar_modelos
```

| Modelo | Detecta | **Bloquea mal** | Avisa de más | p50 | Peso |
|---|---|---|---|---|---|
| `gliner_multi-v2.1` (actual) | 23/30 | **0**/54 | 21/54 | 372 ms | 1156 MB |
| `gliner_multi_pii-v1` | 25/30 | **0**/54 | 22/54 | 393 ms | 1156 MB |
| `gliner_medium-v2.1` | 22/30 | **0**/54 | 18/54 | 402 ms | 781 MB |
| **`gliner_small-v2.1`** | **26/30** | **0**/54 | 21/54 | **294 ms** | **611 MB** |

*(Las latencias están infladas: los cuatro modelos estaban cargados en memoria a
la vez. Medido solo, el actual da p50 126 ms.)*

**Lo que dice la tabla, y lo que no.** Con 30 frases sensibles, la diferencia
entre 22 y 26 son cuatro frases: **eso es ruido, no una jerarquía.** Lo que sí es
sólido es que **los cuatro bloquean cero trabajo legítimo**, y que el peso y la
velocidad se diferencian de verdad.

**Conclusión 1: sí, conviene otro modelo, pero no por detectar más.**
`gliner_small-v2.1` pesa la cuarta parte y es más rápido, sin que se pueda medir
que detecte menos. En un producto que se instala en el equipo de cada empleado,
1.7 GB menos por máquina es una diferencia real y la detección extra del modelo
grande no lo es. Falta confirmarlo con un corpus más grande antes de cambiar el
default: `gliner_small` está construido sobre un DeBERTa en inglés, y que gane en
español con 30 frases es justamente el tipo de resultado que se da vuelta cuando
el corpus crece.

**Conclusión 2: no, no hay que afinar nada todavía**, y la razón no es "más
adelante". Es esta: **lo que el modelo falla no se arregla entrenando.**

- Las credenciales las erraba porque una contraseña **no es un tipo de entidad**.
  `Temporal#2026` no se parece a nada; es secreta por el contexto, no por su
  forma. Un extractor de entidades nunca va a ser la herramienta. Se resolvió con
  dos reglas deterministas, y la cascada pasó de dejar escapar 2 de 3 a **8/8**.
- Lo que marca de más es siempre lo mismo: **no distingue mencionar de filtrar.**
  *"Explicame qué hace Bancolombia"* y un contrato con Bancolombia tienen la
  misma entidad. Eso no es un déficit de entrenamiento, es que la tarea está mal
  planteada: reconocer entidades no es lo mismo que juzgar si algo es una fuga.
  Afinar GLiNER con más ejemplos lo haría más seguro de sí mismo sobre la
  pregunta equivocada.
- Y el argumento que cierra el caso: **con 30 frases sensibles no se puede medir
  si un fine tuning sirvió.** Una mejora de tres frases es indistinguible del
  azar. Entrenar sin poder medir es gastar en fe.

**El orden correcto, entonces:** (1) crecer el corpus con casos reales del
negocio, (2) con ese corpus, decidir el modelo con una diferencia que se pueda
creer, (3) recién ahí evaluar fine tuning — y si se hace, sobre la tarea correcta
(clasificar "¿esto es una fuga?"), no sobre extracción de entidades.

**Y lo más importante: el modelo no es lo que protege.** La cascada completa,
medida sobre el corpus, deja escapar **1 de 30** y bloquea **0 de 54** frases
legítimas. Las credenciales, las cédulas y los exports los ve T1 con certeza. El
modelo agrega los casos sin formato, y por eso avisa en vez de cortar.

## 10. Variables

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AEGIS_T2` | apagado | `1` prende el modelo |
| `AEGIS_T2_MODELO` | `urchade/gliner_multi-v2.1` | Identificador de Hugging Face o ruta local |
| `AEGIS_T2_ACCION` | `block` | `warn` para que ningún hallazgo del modelo bloquee, sin importar la categoría |
