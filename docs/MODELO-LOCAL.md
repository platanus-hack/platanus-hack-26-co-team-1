# El modelo local (nivel T2)

Todo lo que hace falta para instalarlo, entender qué hace, medirlo y refinarlo.

---

## 1. Qué es y qué no es

**Es** un extractor de entidades de ~50M de parámetros que corre en CPU:
[`urchade/gliner_multi-v2.1`](https://huggingface.co/urchade/gliner_multi-v2.1).

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

El modelo se descarga solo la primera vez que se usa (~500 MB desde Hugging Face,
unos 20 segundos de carga en frío). Queda en la caché de `huggingface_hub`, así
que la segunda vez arranca directo.

**Está apagado por defecto.** Se prende con:

```bash
AEGIS_T2=1
```

Arrancar descargando medio giga la primera vez que alguien abre un chat sería una
forma rara de presentarse, y el agente protege igual sin él.

## 3. Las etiquetas

El modelo recibe las etiquetas **como texto**, así que agregar un tipo de dato es
configuración de la empresa y no un release del producto.

| Etiqueta | Categoría | Severidad |
|---|---|---|
| `contrasena` | secret | critical |
| `empresa` | internal_data | high |
| `organizacion` | internal_data | high |
| `dinero` | internal_data | high |
| `enfermedad` | pii | high |
| `persona` | pii | medium |
| `direccion` | pii | medium |

**Van cortas a propósito, y esto es lo más importante de este documento.** Medido
con este mismo modelo:

| Etiqueta larga | Resultado | Etiqueta corta | Resultado |
|---|---|---|---|
| `nombre de cliente o empresa` | 0.37 sobre la palabra equivocada | `empresa` | **0.70** sobre "Grupo Exito" |
| `diagnostico medico` | no encuentra nada | `enfermedad` | **0.87** sobre "hipertension" |
| `nombre de persona` | 0.70 | `persona` | **0.95** |

Una etiqueta descriptiva se lee mejor en el código y le funciona peor al modelo.
Si vas a agregar una, medila antes de darla por buena.

## 4. Métricas medidas

Con `bench/evaluar_modelo.py` sobre 7 frases sensibles y 10 de trabajo normal en
español, en CPU sin GPU:

| Umbral | Detecta | Falsos positivos |
|---|---|---|
| 0.50 | 7/7 | **0**/10 |
| 0.60 (actual) | 6/7 | **0**/10 |
| 0.75 | 4/7 | **0**/10 |

```
Latencia:  p50 108 ms | p95 118 ms | presupuesto 700 ms
Carga:     ~17 s en frío, una sola vez por proceso
```

**Por qué 0.6 y no 0.5**, que midió mejor: el corpus son 17 frases escritas a
mano. Con un corpus real de la empresa esto se decide con datos y no con
prudencia. Mientras tanto, el margen.

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
3. **Advierte, no bloquea.** T1 detecta con certeza y el modelo con probabilidad.
   Frenarle el trabajo a alguien por una probabilidad es la forma más rápida de
   que desinstalen Aegis. Se sube a bloqueo con `AEGIS_T2_ACCION=block`.

Y una cuarta, implícita: **si no está instalado, el agente funciona igual.** Hay
tests que verifican que el motor sigue detectando todo lo de T1 con el modelo
ausente, caído o lento.

## 7. Cómo refinarlo

Por orden de lo que más rinde:

**a. Corpus propio en español.** Es lo que más falta. Ampliá las dos listas de
`bench/evaluar_modelo.py` con frases reales del negocio (anonimizadas) y volvé a
medir los umbrales. 17 frases no alcanzan para decidir nada con confianza.

**b. Etiquetas del negocio.** `AEGIS_T2_ETIQUETAS` no existe todavía, pero
`scan_model()` ya recibe las etiquetas como parámetro: exponerlo en la política de
la empresa es un cambio chico. Candidatas obvias: `numero de poliza`,
`numero de contrato`, `codigo de proyecto`.

**c. Un modelo más chico.** `gliner_small-v2.1` (~50M) pesa menos que el multi y
puede alcanzar si el corpus es solo español. Se cambia con `AEGIS_T2_MODELO`.

**d. Exportar a ONNX cuantizado.** Bajaría el peso en disco y la RAM. Vale la
pena cuando haya que distribuirlo en un instalador; hoy `pip install` lo resuelve.

**e. Afinar el modelo.** Solo con corpus etiquetado propio, y solo si a, b y c ya
se agotaron. Antes de entrenar nada, medí: puede que no haga falta.

## 8. Sobre distribuir los pesos

No publicamos los pesos en una release del repo. El modelo es de terceros, ya está
en Hugging Face y bajarlo desde ahí es una línea. Lo que sí es nuestro y vale la
pena versionar es **la configuración**: etiquetas, umbral, mapeo a categorías y el
arnés de evaluación, y todo eso está en el repo.

Si más adelante afinamos un modelo propio con corpus de la empresa, ahí sí tiene
sentido una release con los pesos, y el lugar natural es `AEGIS_T2_MODELO`
apuntando a una ruta local en vez de a un identificador de Hugging Face.

## 9. Variables

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AEGIS_T2` | apagado | `1` prende el modelo |
| `AEGIS_T2_MODELO` | `urchade/gliner_multi-v2.1` | Identificador de Hugging Face o ruta local |
| `AEGIS_T2_ACCION` | `warn` | `block` para que sus hallazgos bloqueen |
