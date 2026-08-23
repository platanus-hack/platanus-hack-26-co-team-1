import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * El resumen pedagogico del panel: que patron de riesgo hay, que area esta
 * menos familiarizada con las herramientas, y que hacer al respecto.
 *
 * Lo calcula el backend (`backend/aegis_backend/insights.py`) a partir de las
 * mismas metricas agregadas de `/api/metrics` -nunca ve una persona, ni
 * siquiera un seudonimo- y lo redacta con enfasis pedagogico: entender antes de
 * castigar. Mismo criterio de degradacion que el resto del panel: sin API o sin
 * modelo configurado, el backend ya resuelve un respaldo escrito a mano, asi
 * que el peor caso acá es "no llegó nada nuevo todavía", nunca una pantalla vacía.
 */

export interface InsightItem {
  titulo: string;
  detalle: string;
  foco?: string;
  tipo?: 'riesgo' | 'adopcion';
}

export interface EstrategiaItem {
  titulo: string;
  detalle: string;
  publico?: string;
}

export interface ResumenPedagogico {
  resumen: string;
  insights: InsightItem[];
  estrategias: EstrategiaItem[];
  /** 'modelo' | 'cache' | 'estatico': de donde salio el texto. */
  generado_por: string;
}

@Injectable({ providedIn: 'root' })
export class InsightsService {
  private readonly sesion = inject(SesionService);

  readonly resumen = signal<ResumenPedagogico | null>(null);
  readonly cargando = signal(false);

  async cargar(rango?: { desde?: string; hasta?: string }): Promise<void> {
    this.cargando.set(true);
    try {
      const parametros = new URLSearchParams();
      if (rango?.desde) parametros.set('desde', rango.desde);
      if (rango?.hasta) parametros.set('hasta', rango.hasta);
      const query = parametros.toString();
      const respuesta = await fetch(`/api/insights${query ? '?' + query : ''}`, {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      if (respuesta.ok) {
        this.resumen.set(await respuesta.json());
      }
    } catch {
      // Sin API queda lo que ya habia. El resto del panel sigue funcionando
      // aunque esta seccion no tenga nada que mostrar todavia.
    } finally {
      this.cargando.set(false);
    }
  }
}
