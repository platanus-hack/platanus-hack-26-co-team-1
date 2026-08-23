import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';

/**
 * Alta de una empresa: la cuenta, su admin y el código de su primer equipo.
 *
 * El formulario de registro existía desde hacía rato y terminaba en un
 * `router.navigateByUrl`: se llenaban tres pasos, se apretaba "Crear cuenta" y
 * no se creaba nada. Quedaba una demo que se ve igual que el producto, que es
 * la peor clase de pantalla — nadie puede notar la diferencia hasta que la usa
 * de verdad.
 *
 * Las tres cosas se crean juntas y no en tres pantallas: una empresa sin admin
 * no se puede mirar, y un admin sin código no tiene cómo sumar un equipo.
 * Separarlas sólo produce estados a medias que alguien tiene que recordar
 * completar.
 */

export interface Registro {
  tenant: string;
  token: string;
  /** El código para el primer equipo. Se muestra una vez, al terminar. */
  codigo: string;
}

@Injectable({ providedIn: 'root' })
export class RegistroService {
  private readonly sesion = inject(SesionService);

  readonly creando = signal(false);
  readonly error = signal<string | null>(null);
  /** El código del primer equipo, para mostrarlo apenas se crea la cuenta. */
  readonly codigoInicial = signal<string | null>(null);

  async crear(empresa: string, usuario: string, password: string): Promise<boolean> {
    this.creando.set(true);
    this.error.set(null);
    let ok = false;
    try {
      const respuesta = await fetch('/v1/registro', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ empresa, usuario, password }),
      });
      const datos = await respuesta.json().catch(() => ({}));
      if (respuesta.ok) {
        // Se entra directo: pedirle a alguien que se loguee justo después de
        // elegir su contraseña es hacerle escribir dos veces lo mismo.
        this.sesion.adoptar(datos.token, datos.tenant, usuario);
        this.codigoInicial.set(datos.codigo ?? null);
        ok = true;
      } else {
        this.error.set(datos.error ?? 'No se pudo crear la cuenta.');
      }
    } catch {
      this.error.set('No se pudo hablar con el servidor.');
    }
    this.creando.set(false);
    return ok;
  }
}
