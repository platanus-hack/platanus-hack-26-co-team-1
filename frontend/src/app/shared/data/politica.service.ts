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
 * Dos cosas que conviene tener presentes al tocar esto:
 *
 * 1. **Se manda la política entera, nunca un campo suelto.** El backend fusiona
 *    contra la que ya existe, así que un `PUT` parcial no borra nada; pero
 *    mandar todo hace que lo que se ve en pantalla y lo que queda guardado sean
 *    lo mismo, sin depender de esa fusión.
 *
 * 2. **`company_terms` es la lista más sensible que tiene la empresa**: nombres
 *    de clientes, proyectos sin anunciar, dominios internos. Viaja por acá
 *    porque es parte de la política, y por eso la pantalla que la edita está
 *    detrás de la sesión igual que todo lo demás.
 */

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
  blind_spot_action: string;
  unknown_domain_action: string;
  unapproved_ai_action: string;
  model_action: string;
  model_threshold: number;
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
  blind_spot_action: 'warn',
  unknown_domain_action: 'warn',
  unapproved_ai_action: 'warn',
  model_action: 'block',
  model_threshold: 0.7,
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
