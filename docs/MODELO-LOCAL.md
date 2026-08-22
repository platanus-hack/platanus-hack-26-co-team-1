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

| Etiqueta | Categoría | Severidad | Qué hace |
|---|---|---|---|
| `nombre de cliente` | internal_data | high | **corta** el envío |
| `credencial` | pii | high | advierte |
| `condicion de salud` | pii | high | advierte |
| `persona` | pii | medium | advierte |
| `empleado` | pii | medium | advierte |
| `domicilio` | pii | medium | advierte |

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

Con `bench/evaluar_modelo.py` sobre el corpus completo (25 sensibles, 36 de
trabajo normal), en CPU sin GPU, dándole al modelo el prompt ya extraído:

| Umbral | Detecta | Bloquea trabajo normal | Advierte de más |
|---|---|---|---|
| 0.50 (actual) | 10/25 | **0**/36 | 4/36 |
| 0.60 | 9/25 | **0**/36 | 3/36 |

```
Latencia:  p50 89 ms | p95 101 ms | presupuesto 700 ms
Carga:     ~5 s, en un hilo al arrancar el proxy y no en el primer envío
```

**Lo que hay que saber para no sobrevender esto.** El modelo cubre bien los datos
personales y de salud (8/8 en el corpus) y muy mal los datos de negocio (1/14):
las etiquetas que los encontraban son justo las que bloqueaban trabajo legítimo.
La configuración actual elige **no equivocarse** por encima de **detectar más**,
porque un bloqueo falso delante de alguien que está trabajando es lo que hace que
Aegis se desinstale.

Dos mediciones anteriores de este documento eran engañosas y quedan anuladas:
estaban hechas sobre 17 frases y sobre el cuerpo crudo del request. Con el JSON
completo el modelo marcaba 8 de cada 10 frases normales, porque los nombres de
parámetros le daban entidades por todos lados.

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
| `AEGIS_T2_ACCION` | `block` | `warn` para que ningún hallazgo del modelo bloquee, sin importar la categoría |
