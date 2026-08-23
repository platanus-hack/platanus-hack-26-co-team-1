import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * Quién entra al panel de esta empresa, y con qué permiso.
 *
 * Hasta acá había UNA cuenta por empresa: la que crea el registro. El rol se
 * emitía en el token, se guardaba y se devolvía acá, pero no existía forma de
 * crear una segunda cuenta — así que `lector` era inalcanzable y la única
 * cuenta posible era administradora. Un rol que no se puede asignar no es un
 * permiso, es un campo.
 *
 * Dos cosas del contrato que conviene tener presentes:
 *
 * 1. **El tenant no viaja nunca.** El servidor lo saca del token firmado, igual
 *    que en todo lo demás. Mandarlo desde acá sería darle a cualquiera la forma
 *    de administrar el equipo de otra empresa cambiando un campo.
 * 2. **Los errores del servidor se muestran tal cual.** Son un solo motivo a
 *    propósito y ya están escritos para que los lea una persona; reemplazarlos
 *    por un "algo salió mal" acá sólo borra la única pista útil.
 */

export type Rol = 'admin' | 'lector';

export interface Usuario {
  usuario: string;
  rol: Rol;
}

@Injectable({ providedIn: 'root' })
export class UsuariosService {
  private readonly sesion = inject(SesionService);

  readonly usuarios = signal<Usuario[]>([]);
  readonly cargando = signal(false);
  readonly guardando = signal(false);
  readonly error = signal<string | null>(null);
  /** Quién soy, para no ofrecerme darme de baja a mí misma. */
  readonly yo = signal('');

  async cargar(): Promise<void> {
    this.cargando.set(true);
    try {
      const respuesta = await fetch('/v1/usuarios', {
        headers: { Accept: 'application/json', ...this.sesion.cabeceras() },
      });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        this.usuarios.set(datos.usuarios ?? []);
        this.yo.set(datos.yo ?? '');
      }
    } catch {
      // Sin API queda la lista que había; la pantalla se puede seguir mirando.
    }
    this.cargando.set(false);
  }

  /** Suma a alguien al equipo. Devuelve si entró. */
  async sumar(usuario: string, password: string, rol: Rol): Promise<boolean> {
    return this.escribir({ usuario, password, rol });
  }

  async cambiarRol(usuario: string, rol: Rol): Promise<boolean> {
    return this.escribir({ usuario, rol });
  }

  async darDeBaja(usuario: string): Promise<boolean> {
    return this.escribir({ usuario, baja: true });
  }

  private async escribir(cuerpo: Record<string, unknown>): Promise<boolean> {
    this.guardando.set(true);
    this.error.set(null);
    let ok = false;
    try {
      const respuesta = await fetch('/v1/usuarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.sesion.cabeceras() },
        body: JSON.stringify(cuerpo),
      });
      const datos = await respuesta.json().catch(() => ({}));
      ok = respuesta.ok;
      if (ok) {
        await this.cargar();
      } else {
        this.error.set(datos.error ?? 'No se pudo guardar el cambio.');
      }
    } catch {
      this.error.set('No se pudo hablar con el servidor.');
    }
    this.guardando.set(false);
    return ok;
  }
}
