# Operación

Cómo levantar cada pieza, en qué orden, y todas las variables de entorno.

---

## 1. Preparar el entorno

Requiere Python 3.11 o superior.

```bash
cd agent
python -m pip install -r requirements.txt   # mitmproxy y playwright
python -m playwright install chromium
python -m pip install gliner onnxruntime    # opcional: el modelo local
```

El motor de detección en sí no tiene dependencias externas: corre con la
biblioteca estándar. Lo de arriba es el proxy, los tests de navegador y T2.

## 2. Correr los tests

```bash
python run_tests.py                              # desde la raíz: agente + backend
cd agent && python -m unittest discover -s tests -t .
cd agent && python -m unittest tests.test_evasion # una sola suite
```

225 tests. Los que necesitan el modelo se saltan solos si no está instalado.

## 3. La demo sin instalar nada

La forma más rápida de ver el producto funcionando:

```bash
cd agent
python -m demo.run
```

Levanta el proxy y abre un Chromium ya configurado, con sitios simulados para los
cuatro casos: IA aprobada, IA no aprobada, dominio desconocido con forma de IA y
sitio interno. No toca tu sistema y no sale tráfico a ningún tercero.

## 4. Instalarlo en el sistema (Windows)

```bash
cd agent
python -m aegis_agent.install.windows plan        # qué va a hacer, antes de hacerlo
python -m aegis_agent.install.windows install     # CA + proxy + variables
python -m aegis_agent.install.windows status      # cómo está ahora
python -m aegis_agent.install.windows uninstall   # revierte todo
```

Todo a nivel de usuario: la CA va al almacén personal y el proxy a HKCU. Se
revierte sin permisos de administrador.

**Windows exige confirmación humana para instalar una CA raíz.** Si el diálogo se
cancela, el instalador **no activa el proxy del navegador** — activarlo con la CA
sin confiar dejaría un aviso de certificado en cada sitio HTTPS. En ese caso corré
el comando que imprime y aceptá el diálogo:

```
certutil -addstore -user Root "C:\Users\<vos>\.mitmproxy\mitmproxy-ca-cert.cer"
```

Verificar con el navegador del sistema:

```bash
python -m demo.verificar_instalacion
```

## 5. Levantar las piezas

Con el proxy instalado en el sistema, **mantenelo corriendo**: si el proxy del
navegador está activo y el proceso muere, no hay navegación.

```bash
# El proxy (el agente propiamente dicho)
mitmdump --listen-port 8899 --set connection_strategy=lazy -s agent/aegis_mitm.py

# El backend: base colaborativa de dominios
cd backend && python -m aegis_backend.app        # :8686

# El panel local
cd agent && python -m aegis_agent.panel.server   # :8787
```

En Windows, para dejarlos corriendo desacoplados de la terminal:

```powershell
Start-Process -FilePath mitmdump.exe -ArgumentList "--listen-port","8899",`
  "--set","connection_strategy=lazy","-s","$agent\aegis_mitm.py" -WindowStyle Hidden
```

## 6. La batería de credenciales

Dispara 34 credenciales de prueba de proveedores distintos contra el proxy que
esté levantado y reporta qué se escapa. Todos los valores son falsos.

```bash
cd agent && python -m demo.bateria_credenciales
```

Debe dar **34 de 34**. Si alguna se escapa, es un hueco real.

## 7. Variables de entorno

### El agente

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AEGIS_MODO` | `equilibrado` | `estricto` corta el destino de las IA no aprobadas |
| `AEGIS_QUEUE` | `aegis-events.jsonl` | Dónde se escribe la cola de eventos |
| `AEGIS_USER` | `u_demo` | Seudónimo de la persona |
| `AEGIS_AREA` | `marketing` | Área, para los agregados del panel |
| `AEGIS_BACKEND` | `http://127.0.0.1:8686` | Base colaborativa de dominios |
| `AEGIS_BACKEND_DISABLED` | — | `1` para no consultar la base |
| `AEGIS_DOMAIN_CACHE` | `aegis-domains-cache.json` | Caché local de veredictos |
| `AEGIS_EVENTS_URL` | — | Panel remoto al que subir los eventos |
| `AEGIS_T2` | apagado | `1` prende el modelo local |
| `AEGIS_T2_MODELO` | `urchade/gliner_multi-v2.1` | Qué modelo cargar |
| `AEGIS_T2_ACCION` | `block` | `warn` para que ningún hallazgo del modelo bloquee |

### El backend

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AEGIS_DB` | `aegis-domains.json` | Dónde persiste la base de dominios |
| `AEGIS_BACKEND_PORT` | `8686` | Puerto |
| `ANTHROPIC_API_KEY` | — | Si está, clasifica dominios con un modelo en vez de heurística |

### El panel

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AEGIS_PANEL_PORT` | `8787` | Puerto del panel local |
| `AEGIS_TENANT` | `acme` | Nombre de la organización que muestra |
| `PORT` | `10000` | Puerto del servicio desplegado; lo inyecta Render |
| `AEGIS_DATA_DIR` | — | Disco donde persistir los eventos del panel desplegado |
| `AEGIS_KV_URL` / `AEGIS_KV_TOKEN` | — | Almacén compatible con Upstash para el panel desplegado |

## 8. El panel desplegado

https://aegis-panel.onrender.com

Es un servicio web de Render (`render.yaml`), no una función serverless. Con
`autoDeploy` encendido cada push a `main` lo redespliega solo; no hay comando que
correr a mano.

```bash
# Estado del servicio y del último despliegue
curl -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/services/srv-da4p6mc9v7es738sehog
```

| Ruta | Qué devuelve |
|---|---|
| `/` | El panel |
| `/api/metrics` | Las métricas en JSON |
| `/v1/health` | Estado y tipo de almacenamiento |
| `POST /v1/events` | Ingesta de eventos redactados (rechaza con 422 los que traigan contenido) |

Para que el agente local suba ahí:

```bash
AEGIS_EVENTS_URL=https://aegis-panel.onrender.com/v1/events
```

**El `.gitignore` excluye los `.jsonl` a propósito**: la cola local tiene la
navegación real de quien esté probando y no puede terminar en un repositorio ni
en un despliegue.

El almacenamiento tiene tres niveles y el servicio elige el primero disponible:
`AEGIS_KV_URL` (externo, sobrevive a todo), `AEGIS_DATA_DIR` (un disco de Render
montado, sobrevive a los reinicios) y, si no hay ninguno, memoria. **El plan
gratuito no monta discos**, así que hoy corre en memoria y pierde los eventos
cuando la instancia se apaga por inactividad. `GET /v1/health` dice cuál está en
uso.

## 9. Los dos modos

| Modo | Con una IA no aprobada |
|---|---|
| `equilibrado` (por defecto) | Abre normal. Cada envío se analiza: el trabajo pasa, el dato sensible no. El uso queda registrado igual. |
| `estricto` | Corta el destino. |

## 10. Diagnóstico rápido

| Síntoma | Dónde mirar |
|---|---|
| El navegador no navega | ¿Está corriendo el proxy? Si no, `install.windows uninstall` |
| Avisos de certificado en todos los sitios | La CA no quedó confiada: `install.windows status` |
| Un sitio se bloquea y no debería | Mirá la cola de eventos: `rule_id` dice qué regla lo marcó |
| El panel está vacío | Sin eventos muestra la semana de demostración; si hay eventos reales los prefiere |
| Todo pasa sin bloquear | ¿El destino está clasificado como IA? `classify()` en `policy.py` |
