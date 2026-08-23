import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * La política de la empresa: lo que el agente obedece en cada equipo.
 *
 * La pantalla de Políticas era un formulario que no salía de la memoria del
 * navegador: se llenaba, se guardaba, y al recargar volvía a estar como antes.
 * La cañería estaba de los dos lados desde hace rato —`Policy.a_dict()`,
 * `policy_store`, `PUT /v1/policy/{tenant}`— y faltaba justo el cable.
 *
 * Tres cosas que conviene tener presentes al tocar esto:
 *
 * 1. **Se manda la política entera, nunca un campo suelto.** `PolicyStore.put`
 *    (`backend/aegis_backend/store.py`) NO fusiona: guarda el dict que llega
 *    tal cual, reemplazando el anterior entero. La fusión contra los defaults
 *    (`Policy.desde_dict(datos, base=...)`) pasa del lado del agente, al leer
 *    -no acá-, así que un campo que esta interfaz no conozca se pierde en el
 *    primer guardado que haga cualquiera desde esta pantalla, no solo en el
 *    que lo tocó. Por eso `Politica` tiene que declarar TODOS los campos de
 *    `Policy.a_dict()`, tengan o no un control propio en la UI.
 *
 * 2. **`company_terms` es la lista más sensible que tiene la empresa**: nombres
 *    de clientes, proyectos sin anunciar, dominios internos. Viaja por acá
 *    porque es parte de la política, y por eso la pantalla que la edita está
 *    detrás de la sesión igual que todo lo demás.
 *
 * 3. **`forbidden_terms` no es `company_terms` con otro nombre.** Producen
 *    hallazgos distintos con perillas distintas -`empresa_*` con
 *    `company_terms_action`, `termino_prohibido` con `block_categories`/
 *    `warn_categories` vía `forbidden_terms_category`- y el motor los mantiene
 *    separados a propósito (ver `detect/ruleset.py`). No hay que fundirlos acá.
 */

/** Una regla propia de la empresa. La regex se compila en `detect/ruleset.py`:
 * si es inválida, el motor la descarta sola sin romper nada. */
export interface ReglaPersonalizada {
  id: string;
  pattern: string;
  category: string;
  severity: string;
}

export interface Politica {
  tenant_id?: string;
  approved_ai: string[];
  blocked_domains: string[];
  rule_actions: Record<string, string>;
  user_actions: Record<string, string>;
  area_actions: Record<string, string>;
  app_actions: Record<string, string>;
  company_terms: Record<string, string>;
  company_terms_action: string;
  injection_action: string;
  /**
   * Qué categorías de una regla de FORMATO (T1: AWS key, tarjeta, contraseña…)
   * cortan el envío. Lo que no esté en ninguna de las dos listas deja pasar.
   */
  block_categories: string[];
  warn_categories: string[];
  /**
   * Reglas T1 apagadas por id. Es la otra forma de decir lo mismo que
   * `rule_actions[id] === 'off'` -el motor une las dos-, y viaja acá sin
   * control propio en la pantalla para que guardar la política no borre lo
   * que se haya apagado por otra vía (por ejemplo, la API).
   */
  disabled_rules: string[];
  /**
   * Términos literales prohibidos: un textarea, una categoría compartida para
   * todos. No es lo mismo que `company_terms` -esa produce un hallazgo por
   * término, con su propia etiqueta y su propia perilla-, así que viven
   * aparte aunque las dos vengan del mismo lugar de la pantalla.
   */
  forbidden_terms: string[];
  forbidden_terms_category: string;
  /** Reglas regex propias de la empresa. */
  custom_rules: ReglaPersonalizada[];
  /** Qué etiquetas busca el modelo local (T2) cuando lee texto sin forma fija. */
  model_labels: string[];
  /**
   * Qué categorías y qué etiquetas del modelo tienen autoridad para CORTAR.
   * Lo que el modelo encuentra y no está acá solo advierte: un hallazgo
   * probabilístico no puede frenar con la misma autoridad que una regla de
   * formato.
   */
  model_block_categories: string[];
  model_block_labels: string[];
  /**
   * Si se lee el texto de las imágenes que salen del equipo.
   *
   * Apagado por defecto: cuesta ~2 s por imagen, así que es una decisión de la
   * empresa. Vive acá y no en una variable de entorno porque `ocr_action` ya
   * está en el panel, y elegir qué hacer con lo que se encuentra en una imagen
   * mientras la lectura está apagada por otro lado promete algo que no ocurre.
   */
  ocr_enabled: boolean;
  /**
   * Qué autoridad tiene lo que se leyó de una imagen.
   *
   * Es la tercera detección probabilística del sistema, junto con el modelo
   * local y la inyección, y hasta acá era la única sin freno.
   */
  ocr_action: string;
  blind_spot_action: string;
  unknown_domain_action: string;
  unapproved_ai_action: string;
  model_action: string;
  model_threshold: number;
  /**
   * Las cuentas de la empresa en las herramientas aprobadas.
   *
   * `approved_ai` dice "ChatGPT se puede usar" y no alcanza: la cuenta personal
   * del empleado entra por el mismo dominio aprobado. Esto declara cuáles
   * cuentas son de la empresa; lo que no esté acá es de otro.
   *
   * Son huellas e identificadores de organización, nunca credenciales: el
   * agente hashea la llave antes de que salga del equipo, así que este campo
   * no puede llevar un secreto ni por error.
   */
  corporate_accounts: string[];
  foreign_account_action: string;
}

const VACIA: Politica = {
  approved_ai: [],
  blocked_domains: [],
  rule_actions: {},
  user_actions: {},
  area_actions: {},
  app_actions: {},
  company_terms: {},
  company_terms_action: 'block',
  injection_action: 'warn',
  block_categories: ['internal_data', 'secret'],
  warn_categories: ['pii'],
  disabled_rules: [],
  forbidden_terms: [],
  forbidden_terms_category: 'internal_data',
  custom_rules: [],
  model_labels: [],
  model_block_categories: ['internal_data', 'secret'],
  model_block_labels: [],
  ocr_enabled: false,
  ocr_action: 'warn',
  blind_spot_action: 'warn',
  unknown_domain_action: 'warn',
  unapproved_ai_action: 'warn',
  model_action: 'block',
  model_threshold: 0.7,
  corporate_accounts: [],
  foreign_account_action: 'warn',
};

@Injectable({ providedIn: 'root' })
export class PoliticaService {
  private readonly sesion = inject(SesionService);

  readonly politica = signal<Politica>(VACIA);
  /** true cuando lo de arriba vino del backend y no del molde vacío. */
  readonly cargada = signal(false);
  readonly guardando = signal(false);
  readonly guardadaEn = signal<string | null>(null);

  async cargar(): Promise<void> {
    const tenant = this.sesion.tenant() || 'acme';
    try {
      const respuesta = await fetch(`/v1/policy/${encodeURIComponent(tenant)}`, {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        // Un tenant sin política guardada devuelve {}: se mezcla con el molde
        // para que la pantalla tenga todos los campos aunque falten en la base.
        this.politica.set({ ...VACIA, ...datos });
        this.cargada.set(Object.keys(datos).length > 0);
      }
    } catch {
      // Sin API queda el molde vacío y la pantalla se puede seguir mirando.
    }
  }

  /** Aplica un cambio y lo persiste. Devuelve si el backend lo aceptó. */
  async guardar(cambio: Partial<Politica>): Promise<boolean> {
    const tenant = this.sesion.tenant() || 'acme';
    const completa = { ...this.politica(), ...cambio, tenant_id: tenant };

    this.guardando.set(true);
    let ok = false;
    try {
      const respuesta = await fetch(`/v1/policy/${encodeURIComponent(tenant)}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...this.sesion.cabeceras(),
        },
        body: JSON.stringify(completa),
      });
      ok = respuesta.ok;
      if (ok) {
        this.politica.set(completa);
        this.cargada.set(true);
        this.guardadaEn.set(new Date().toLocaleTimeString('es', { timeStyle: 'short' }));
      }
    } catch {
      // ok queda en false y la pantalla lo dice.
    }
    this.guardando.set(false);
    return ok;
  }
}
