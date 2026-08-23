# Documentación de Aegis

Si venís a retomar el proyecto sin haber estado antes, empezá por
**[ESTADO.md](ESTADO.md)**: dice qué funciona, qué falta y qué bugs ya
encontramos para que no los reintroduzcas.

| Documento | Para qué |
|---|---|
| [ESTADO.md](ESTADO.md) | Relevo: estado actual, huecos conocidos, por dónde seguir |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Cómo encaja todo y por dónde pasa un request |
| [OPERACION.md](OPERACION.md) | Cómo levantar cada pieza y todas las variables |
| [MODELO-LOCAL.md](MODELO-LOCAL.md) | El nivel T2: instalación, etiquetas, métricas, cómo refinarlo |
| [00-propuesta.md](00-propuesta.md) | El producto: problema, propuesta y requisitos del MVP |
| [adr/](adr/) | Las decisiones de arquitectura y por qué se tomaron |
| [spec/contrato-de-datos.md](spec/contrato-de-datos.md) | Qué cruza la frontera entre el equipo y la nube |

Las investigaciones que sustentan las decisiones viven **fuera del repo**, en
`../investigacion/`: son notas de trabajo, no parte del producto.

- `01-interceptacion-de-trafico.md` — cómo interceptar en navegador y escritorio
- `02-motor-de-deteccion.md` — qué corre local y qué no
- `03-competencia-y-la-brecha-abierta.md` — el nicho y por qué la brecha sigue abierta
- `04-modelo-local-optimo.md` — elección del modelo
