import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * Las metricas de verdad, del agente que corre en los equipos.
 *
 * El panel de admin nacio con datos de ejemplo escritos en el componente, que
 * sirven para disenar pero no para demostrar nada. Esto los reemplaza por lo que
 * el agente esta viendo de verdad, sin perder la version de ejemplo: si el API
 * no responde -porque se abrio el front suelto con `ng serve`, o porque el
 * servicio esta arrancando- se queda con la maqueta y el panel se ve igual.
 *
 * Mismo criterio que el resto de Aegis: degradar, nunca romper.
 */

/** Un [nombre, valor] de los rankings del panel. */
export interface Ranking {
  nombre: string;
  valor: number;
}

/** Un destino con su clasificacion, que es lo que decide si preocupa o no. */
export interface Destino {
  dominio: string;
  clasificacion: string;
  intentos: number;
}

export interface MetricasPanel {
  total: number;
  bloqueados: number;
  advertidos: number;
  tasaBloqueo: number;
  /** Que TIPO de dato se intento sacar. Es el dato mas propio de Aegis. */
  detecciones: Ranking[];
  destinos: Destino[];
  areasVulnerables: Ranking[];
  /** Cuánto usa la IA cada área: el total, no sólo lo que se le escapa. */
  areasUsoIa: Ranking[];
  /** Con qué herramienta, no hacia qué dominio. Son cosas distintas. */
  herramientas: Ranking[];
  /** Dominios que nadie catalogo y que se delataron por su comportamiento. */
  shadowAi: string[];
  /** true cuando esto vino del agente y no de la maqueta. */
  enVivo: boolean;
}

/** Lo que se muestra cuando no hay API. Disenar necesita datos; demostrar, no. */
const MAQUETA: MetricasPanel = {
  total: 0,
  bloqueados: 0,
  advertidos: 0,
  tasaBloqueo: 0,
  detecciones: [],
  destinos: [],
  areasVulnerables: [
    { nombre: 'Contabilidad', valor: 18 },
    { nombre: 'Ventas', valor: 12 },
    { nombre: 'Ingeniería', valor: 7 },
    { nombre: 'Marketing', valor: 4 },
  ],
  areasUsoIa: [
    { nombre: 'Ingeniería', valor: 86 },
    { nombre: 'Marketing', valor: 61 },
    { nombre: 'Contabilidad', valor: 40 },
    { nombre: 'RR.HH.', valor: 22 },
  ],
  herramientas: [
    { nombre: 'Claude', valor: 48 },
    { nombre: 'ChatGPT', valor: 33 },
    { nombre: 'Claude Code', valor: 14 },
    { nombre: 'Copilot', valor: 5 },
  ],
  shadowAi: [],
  enVivo: false,
};

/** Nombres legibles para los rule_id del motor. */
const NOMBRE_DE_REGLA: Record<string, string> = {
  aws_access_key_id: 'Credencial de AWS',
  anthropic_api_key: 'API key de Anthropic',
  openai_api_key: 'API key de OpenAI',
  github_token: 'Token de GitHub',
  google_api_key: 'API key de Google',
  private_key_block: 'Llave privada',
  db_connection_string: 'Conexión a base de datos',
  generic_secret_assignment: 'Secreto en el código',
  credencial_en_espanol: 'Contraseña en una frase',
  credencial_en_espanol_sin_verbo: 'Contraseña en una frase',
  csv_pii_export: 'Export de datos personales',
  sql_dump_header: 'Volcado de base de datos',
  sql_insert_rows: 'Filas de base de datos',
  bulk_pii_export: 'Export masivo de datos',
  credit_card: 'Tarjeta de crédito',
  latam_national_id: 'Documento de identidad',
  email_address: 'Correo electrónico',
  archivo_critico: 'Archivo crítico',
  archivo_critico_por_firma: 'Base de datos disfrazada',
  punto_ciego: 'App que esquiva el proxy',
};

/**
 * Nombres legibles para lo que el agente reporta en `destination.process`.
 *
 * El agente normaliza a un identificador estable (`procesos.py`) para que la
 * política sea portable entre sistemas operativos; acá se deshace sólo para
 * mostrarlo. La política sigue hablando de `claude-code`, no de "Claude Code".
 */
const NOMBRE_DE_PROCESO: Record<string, string> = {
  'claude-code': 'Claude Code',
  'chatgpt-app': 'ChatGPT (app)',
  browser: 'Navegador',
  cursor: 'Cursor',
  copilot: 'Copilot',
  aider: 'Aider',
  ollama: 'Ollama',
  codex: 'Codex',
  desconocido: 'Sin atribuir',
};

/** `modelo:empresa` y `empresa_cliente` son familias, no reglas sueltas. */
function nombreDeRegla(reglaId: string): string {
  let nombre = NOMBRE_DE_REGLA[reglaId];
  if (!nombre) {
    if (reglaId.startsWith('modelo:')) {
      nombre = `Detectado por el modelo: ${reglaId.slice(7).replace(/_/g, ' ')}`;
    } else if (reglaId.startsWith('empresa_')) {
      nombre = `Dato interno: ${reglaId.slice(8).replace(/_/g, ' ')}`;
    } else if (reglaId.startsWith('inyeccion_')) {
      nombre = 'Intento de inyección de prompt';
    } else {
      nombre = reglaId.replace(/_/g, ' ');
    }
  }
  return nombre;
}

@Injectable({ providedIn: 'root' })
export class MetricasService {
  private readonly sesion = inject(SesionService);

  readonly metricas = signal<MetricasPanel>(MAQUETA);
  /** true cuando el API rechazo la sesion: sirve para mandar al login. */
  readonly sinSesion = signal(false);

  /**
   * @param rango Ventana de tiempo en ISO8601 UTC. Sin nada, trae todo lo que
   *   haya. Esto SI va en la llamada -a diferencia del tenant- porque es una
   *   preferencia de quien mira el panel, no un dato que decida a que empresa
   *   pertenecen los eventos.
   */
  async cargar(rango?: { desde?: string; hasta?: string }): Promise<void> {
    try {
      const parametros = new URLSearchParams();
      if (rango?.desde) parametros.set('desde', rango.desde);
      if (rango?.hasta) parametros.set('hasta', rango.hasta);
      const query = parametros.toString();
      // El token va en la cabecera y el tenant NO va en ningun lado: lo saca el
      // servidor de adentro del token firmado. Si fuera un parametro de esta
      // llamada, cualquiera pediria los datos de otra empresa desde la consola.
      const respuesta = await fetch(`/api/metrics${query ? '?' + query : ''}`, {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      this.sinSesion.set(respuesta.status === 401);
      if (respuesta.ok) {
        this.metricas.set(this.traducir(await respuesta.json()));
      }
    } catch {
      // Sin API queda lo que ya habia (la maqueta, si era la primera carga). Un
      // panel sin datos reales sigue siendo un panel; uno que revienta al
      // abrirlo, no.
    }
  }

  /** Del contrato del agente al vocabulario de la pantalla. */
  private traducir(datos: any): MetricasPanel {
    const m = datos?.metrics ?? {};
    const porArea: [string, number, number][] = m.by_area ?? [];

    return {
      total: m.total ?? 0,
      bloqueados: m.blocked ?? 0,
      advertidos: m.warned ?? 0,
      tasaBloqueo: Math.round(m.block_rate ?? 0),
      detecciones: (m.by_rule ?? [])
        .slice(0, 6)
        .map(([regla, veces]: [string, number]) => ({ nombre: nombreDeRegla(regla), valor: veces })),
      destinos: (m.by_destination ?? [])
        .slice(0, 6)
        .map(([dominio, clasificacion, intentos]: [string, string, number]) => ({
          dominio,
          clasificacion,
          intentos,
        })),
      // El segundo numero de by_area son los criticos, que es lo que hace
      // vulnerable a un area: no cuanto usa la IA, sino cuanto se le escapa.
      //
      // Ya no cae a MAQUETA cuando esta vacio: antes "vacio" solo pasaba sin
      // agente conectado, pero con el filtro de rango un area sin incidentes
      // ESTA semana es un resultado real, y tapar eso con Contabilidad/Ventas
      // inventados mentiria justo cuando el filtro funciona.
      areasVulnerables: porArea.map(([nombre, , criticos]) => ({ nombre, valor: criticos })),
      // El primer número de by_area es el uso total y el segundo lo crítico:
      // el mismo dato responde "quién usa más IA" y "a quién se le escapa más",
      // que son preguntas distintas y estaban las dos inventadas.
      areasUsoIa: porArea.map(([nombre, total]) => ({ nombre, valor: total })),
      herramientas: (m.by_process ?? [])
        .slice(0, 6)
        .map(([proceso, veces]: [string, number]) => ({
          nombre: NOMBRE_DE_PROCESO[proceso] ?? proceso,
          valor: veces,
        })),
      shadowAi: (m.shadow_domains ?? []).slice(0, 8),
      // Esto vino de una respuesta real del API, aunque el rango elegido no
      // tenga ningun evento adentro: "en vivo y sin nada que mostrar" no es lo
      // mismo que "no hay API", y antes se confundian los dos casos.
      enVivo: true,
    };
  }
}
