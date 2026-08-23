import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * Los propios intentos de un colaborador, para su propia pantalla.
 *
 * No es `MetricasService` con un filtro: ese servicio es del admin y trae
 * agregados de toda la empresa (`/api/metrics`). Este trae SOLO los eventos
 * cuyo `actor.user_id` es la propia sesión (`/v1/mi-actividad`), que el
 * backend arma mirando el token -nunca un parámetro-, igual que el tenant en
 * todo lo demás.
 */

export interface EntradaActividad {
  occurred_at: string;
  process: string | null;
  domain: string | null;
  classification: string | null;
  action: 'blocked' | 'redacted' | 'warned' | 'allowed' | string;
  rule_id: string | null;
  category: string | null;
  severity: string | null;
}

@Injectable({ providedIn: 'root' })
export class ActividadService {
  private readonly sesion = inject(SesionService);

  readonly entradas = signal<EntradaActividad[]>([]);
  readonly cargando = signal(false);
  /** true cuando lo de arriba vino del API. Sin esto, no hay forma de distinguir "sin intentos" de "sin conexión". */
  readonly cargada = signal(false);

  async cargar(): Promise<void> {
    this.cargando.set(true);
    try {
      const respuesta = await fetch('/v1/mi-actividad', {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        this.entradas.set(datos.actividad ?? []);
        this.cargada.set(true);
      }
    } catch {
      // Sin API queda lo que ya había cargado.
    } finally {
      this.cargando.set(false);
    }
  }
}
