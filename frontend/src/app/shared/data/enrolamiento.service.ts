import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * Los códigos que suman un equipo al panel de esta empresa.
 *
 * Es la pieza que faltaba para que el producto sirva instalado: hasta acá el
 * agente protegía el equipo y no le hablaba a ningún panel, porque nadie le
 * había dicho a cuál. La empresa veía el panel vacío y concluía que nadie usa
 * IA.
 *
 * El código se muestra entero y se puede volver a leer: no es un secreto que se
 * guarde hasheado, es un pasaje de un solo sentido. Quien lo tiene puede sumar
 * un equipo; para LEER lo que ese equipo reporta hace falta una sesión, que es
 * otra credencial.
 */

export interface Codigo {
  codigo: string;
  tenant: string;
  creado_en: number;
  vence_en: number;
  revocado: boolean;
  usos: number;
}

@Injectable({ providedIn: 'root' })
export class EnrolamientoService {
  private readonly sesion = inject(SesionService);

  readonly codigos = signal<Codigo[]>([]);
  readonly generando = signal(false);
  /** El recién creado, para poder destacarlo: es el que la persona va a copiar. */
  readonly ultimo = signal<string | null>(null);

  async cargar(): Promise<void> {
    try {
      const respuesta = await fetch('/v1/enrolamiento', {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        this.codigos.set(datos.codigos ?? []);
      }
    } catch {
      // Sin API la pantalla se puede seguir mirando, vacía.
    }
  }

  async generar(): Promise<string | null> {
    this.generando.set(true);
    let codigo: string | null = null;
    try {
      const respuesta = await fetch('/v1/enrolamiento', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.sesion.cabeceras() },
        body: JSON.stringify({}),
      });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        codigo = datos.codigo ?? null;
        this.ultimo.set(codigo);
        await this.cargar();
      }
    } catch {
      // queda en null y la pantalla no muestra nada nuevo
    }
    this.generando.set(false);
    return codigo;
  }

  /** Con guiones y en mayúsculas, que es como se lee y como se dicta. */
  presentable(codigo: string): string {
    const limpio = codigo.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const sinPrefijo = limpio.startsWith('AEGIS') ? limpio.slice(5) : limpio;
    const grupos = sinPrefijo.match(/.{1,4}/g) ?? [];
    return ['AEGIS', ...grupos].join('-');
  }
}
