import { Injectable, signal } from '@angular/core';

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
  readonly metricas = signal<MetricasPanel>(MAQUETA);

  async cargar(): Promise<void> {
    try {
      const respuesta = await fetch('/api/metrics', { headers: { Accept: 'application/json' } });
      if (respuesta.ok) {
        this.metricas.set(this.traducir(await respuesta.json()));
      }
    } catch {
      // Sin API queda la maqueta. Un panel sin datos reales sigue siendo un
      // panel; uno que revienta al abrirlo, no.
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
      areasVulnerables: porArea.length
        ? porArea.map(([nombre, , criticos]) => ({ nombre, valor: criticos }))
        : MAQUETA.areasVulnerables,
      shadowAi: (m.shadow_domains ?? []).slice(0, 8),
      enVivo: (m.total ?? 0) > 0,
    };
  }
}
