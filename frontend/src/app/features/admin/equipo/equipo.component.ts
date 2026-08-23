import { Component, OnInit, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { Rol, UsuariosService } from '../../../shared/data/usuarios.service';

/**
 * El equipo del panel: quién entra, con qué permiso, y cómo se cambia.
 *
 * Es la pantalla que faltaba para que el rol signifique algo. El backend ya
 * distinguía admin de lector y hacía valer la diferencia en cada escritura,
 * pero sin forma de crear una segunda cuenta la distinción no existía en la
 * práctica.
 *
 * Dos decisiones de la pantalla:
 *
 * - **El alta va en la misma vista que la lista, no detrás de un modal.** Sumar
 *   a alguien es lo primero que se viene a hacer acá; esconderlo detrás de un
 *   clic sólo agrega un paso a la única tarea de la pantalla.
 * - **La contraseña se elige acá y se muestra una sola vez.** No hay mail
 *   saliendo del panel ni invitaciones por link, así que quien la crea tiene
 *   que poder pasársela a la persona. Decirlo en pantalla es más honesto que
 *   dejar que se descubra al recargar.
 */
@Component({
  selector: 'app-equipo',
  standalone: true,
  imports: [CommonModule, FormsModule, BadgeComponent],
  templateUrl: './equipo.component.html',
})
export class EquipoComponent implements OnInit {
  private readonly datos = inject(UsuariosService);

  readonly usuarios = this.datos.usuarios;
  readonly cargando = this.datos.cargando;
  readonly guardando = this.datos.guardando;
  readonly error = this.datos.error;
  readonly yo = this.datos.yo;

  /** Cuántos admins quedan: con uno solo, no se puede sacar ni degradar. */
  readonly admins = computed(() => this.usuarios().filter((u) => u.rol === 'admin').length);

  nuevoUsuario = '';
  nuevaClave = '';
  nuevoRol: Rol = 'lector';
  /** Lo último que se creó, para poder copiarlo y pasarlo. */
  recienCreado: { usuario: string; clave: string } | null = null;

  ngOnInit(): void {
    void this.datos.cargar();
  }

  get puedeSumar(): boolean {
    return this.nuevoUsuario.trim().length > 0 && this.nuevaClave.length >= 8;
  }

  /**
   * Por qué no se puede tocar a esta persona, o null si sí se puede.
   *
   * Devuelve el motivo y no un booleano a propósito: un botón deshabilitado sin
   * explicación es la forma más rápida de que alguien crea que el panel está
   * roto. El servidor rechaza esto igual — acá se dice antes, que es distinto
   * de confiar en el cliente.
   */
  motivoBloqueado(usuario: string, rol: Rol): string | null {
    let motivo: string | null = null;
    if (rol === 'admin' && this.admins() <= 1) {
      motivo = 'Es la única cuenta que puede administrar esta empresa.';
    }
    return motivo;
  }

  async sumar(): Promise<void> {
    const usuario = this.nuevoUsuario.trim().toLowerCase();
    const clave = this.nuevaClave;
    if (await this.datos.sumar(usuario, clave, this.nuevoRol)) {
      this.recienCreado = { usuario, clave };
      this.nuevoUsuario = '';
      this.nuevaClave = '';
      this.nuevoRol = 'lector';
    }
  }

  async alternarRol(usuario: string, rol: Rol): Promise<void> {
    await this.datos.cambiarRol(usuario, rol === 'admin' ? 'lector' : 'admin');
  }

  async darDeBaja(usuario: string): Promise<void> {
    await this.datos.darDeBaja(usuario);
  }

  cerrarAviso(): void {
    this.recienCreado = null;
  }
}
