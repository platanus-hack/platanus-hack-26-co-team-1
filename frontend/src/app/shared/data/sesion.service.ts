import { Injectable, computed, signal } from '@angular/core';

/**
 * Quien entro al panel, y de que empresa ve los datos.
 *
 * El panel era publico: `/admin/panel` lo abria cualquiera y mostraba todos los
 * eventos, de todas las empresas. Para un producto cuyo pitch es "tus datos no
 * salen de tu empresa", que el panel de una muestre el trafico de otra no es un
 * detalle de permisos.
 *
 * Lo que hay que tener claro de este archivo: **el tenant que se muestra abajo
 * es informativo, no es lo que decide que datos llegan**. Eso lo decide el
 * servidor leyendo el tenant de adentro del token firmado. Si esta clase
 * mintiera sobre su tenant, el API seguiria devolviendo los datos de la empresa
 * de verdad: no hay forma de pedir los de otra desde aca.
 */

export interface Sesion {
  token: string;
  usuario: string;
  tenant: string;
  rol: string;
  /** true solo para una cuenta de colaborador recien creada con una temporal. */
  debe_cambiar_password?: boolean;
}

const CLAVE = 'aegis.sesion';

@Injectable({ providedIn: 'root' })
export class SesionService {
  private readonly actual = signal<Sesion | null>(this.recuperar());

  readonly sesion = this.actual.asReadonly();
  readonly autenticado = computed(() => this.actual() !== null);
  readonly usuario = computed(() => this.actual()?.usuario ?? '');
  readonly tenant = computed(() => this.actual()?.tenant ?? '');
  readonly rol = computed(() => this.actual()?.rol ?? '');

  /**
   * La contraseña recién tipeada, SOLO mientras dura la navegación al
   * onboarding obligatorio. Nunca se persiste -ni en localStorage ni en la
   * URL-, así que un refresh de página la pierde a propósito: la pantalla de
   * onboarding vuelve a pedirla en ese caso, en vez de dejarla dando vueltas
   * en un lugar donde podría sobrevivir más de lo que hace falta.
   */
  readonly contrasenaRecien = signal('');

  /** Las credenciales, o un mensaje de por que no. */
  async entrar(usuario: string, password: string): Promise<string | null> {
    let error: string | null = 'No se pudo conectar con el servidor.';
    try {
      const respuesta = await fetch('/v1/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usuario, password }),
      });
      if (respuesta.ok) {
        const sesion: Sesion = await respuesta.json();
        this.actual.set(sesion);
        this.guardar(sesion);
        error = null;
      } else {
        error = 'Usuario o contraseña incorrectos.';
      }
    } catch {
      // Queda el mensaje de conexion.
    }
    return error;
  }

  /** Cambia la propia contraseña. Devuelve un mensaje de error, o null si salió bien. */
  async cambiarPassword(actual: string, nueva: string): Promise<string | null> {
    let error: string | null = 'No se pudo conectar con el servidor.';
    try {
      const respuesta = await fetch('/v1/password', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...this.cabeceras() },
        body: JSON.stringify({ actual, nueva }),
      });
      if (respuesta.ok) {
        error = null;
        // La sesión ya no tiene que frenar en onboarding la próxima vez.
        const previa = this.actual();
        if (previa) {
          const actualizada = { ...previa, debe_cambiar_password: false };
          this.actual.set(actualizada);
          this.guardar(actualizada);
        }
        this.contrasenaRecien.set('');
      } else {
        const datos = await respuesta.json().catch(() => null);
        error = datos?.error ?? 'No se pudo cambiar la contraseña.';
      }
    } catch {
      // Queda el mensaje de conexion.
    }
    return error;
  }

  salir(): void {
    this.actual.set(null);
    try {
      localStorage.removeItem(CLAVE);
    } catch {
      // Un navegador que bloquea el almacenamiento no puede romper el logout.
    }
  }

  /** La cabecera para el API. Vacia si no hay sesion. */
  cabeceras(): Record<string, string> {
    const token = this.actual()?.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  private guardar(sesion: Sesion): void {
    try {
      localStorage.setItem(CLAVE, JSON.stringify(sesion));
    } catch {
      // Sin almacenamiento la sesion dura lo que la pestana, y esta bien.
    }
  }

  private recuperar(): Sesion | null {
    let sesion: Sesion | null = null;
    try {
      const crudo = localStorage.getItem(CLAVE);
      if (crudo) {
        sesion = JSON.parse(crudo) as Sesion;
      }
    } catch {
      sesion = null;
    }
    return sesion;
  }
}
