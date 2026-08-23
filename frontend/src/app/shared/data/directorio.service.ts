import { Injectable, inject, signal } from '@angular/core';
import { SesionService } from './sesion.service';
import { ColaboradorResumen, COLABORADORES } from './colaboradores';

/**
 * La gente de la empresa y las herramientas que corren en ella.
 *
 * Antes esto era `COLABORADORES`: diez personas escritas a mano en un archivo,
 * compartidas por tres pantallas. Servía para diseñar y no demostraba nada,
 * porque el agente estaba viendo otra cosa.
 *
 * El campo que hace que valga la pena es `usuario`. Es el mismo seudónimo que
 * el agente reporta en `actor.user_id`, así que el backend puede contar los
 * intentos de cada persona **sin que ningún evento lleve nunca su nombre**. El
 * panel dice "Marcos reincide con credenciales"; el agente sigue sin saber
 * quién es Marcos.
 *
 * Mismo criterio que el resto: si el API no responde queda la maqueta, porque
 * un panel sin datos reales sigue siendo un panel y uno que revienta no.
 */

export interface Agente {
  clase: 'agente' | 'mcp' | 'skill';
  nombre: string;
  tipo?: string;
  estado: 'aprobado' | 'no-catalogado' | 'bloqueado';
  alcance?: string;
  usuarios: string[];
  ultima_actividad?: string;
}

export interface Empresa {
  tenant: string;
  nombre?: string;
  sector?: string;
  tamano?: string;
  areas: string[];
}

@Injectable({ providedIn: 'root' })
export class DirectorioService {
  private readonly sesion = inject(SesionService);

  readonly gente = signal<ColaboradorResumen[]>(COLABORADORES);
  readonly inventario = signal<Agente[]>([]);
  readonly empresa = signal<Empresa | null>(null);
  /** true cuando lo de arriba vino del API y no de la maqueta. */
  readonly enVivo = signal(false);

  async cargarGente(): Promise<void> {
    const datos = await this.pedir('/v1/colaboradores');
    const filas = datos?.colaboradores ?? [];
    // Lista vacía es un estado legítimo -una empresa recién registrada- pero
    // dejar el panel en blanco en una demo no ayuda a nadie. Con datos reales
    // manda lo real; sin ninguno, la maqueta.
    if (filas.length) {
      this.gente.set(filas.map((f: any) => this.traducir(f)));
      this.enVivo.set(true);
    }
  }

  async cargarInventario(): Promise<void> {
    const datos = await this.pedir('/v1/inventario');
    if (datos?.inventario) {
      this.inventario.set(datos.inventario);
    }
  }

  async cargarEmpresa(): Promise<void> {
    const datos = await this.pedir('/v1/tenant');
    if (datos?.tenant) {
      this.empresa.set(datos as Empresa);
    }
  }

  /** Uno o muchos: el alta manual y el CSV van por la misma puerta. */
  async guardar(filas: Partial<ColaboradorResumen>[]): Promise<number> {
    const datos = await this.pedir('/v1/colaboradores', 'POST', { colaboradores: filas });
    await this.cargarGente();
    return datos?.guardados?.length ?? 0;
  }

  async borrar(usuario: string): Promise<void> {
    await this.pedir(`/v1/colaboradores/${encodeURIComponent(usuario)}`, 'DELETE');
    await this.cargarGente();
  }

  async guardarEmpresa(empresa: Partial<Empresa>): Promise<void> {
    const datos = await this.pedir('/v1/tenant', 'POST', empresa);
    if (datos?.tenant) {
      this.empresa.set(datos as Empresa);
    }
  }

  private traducir(fila: any): ColaboradorResumen {
    return {
      id: fila.usuario,
      nombre: fila.nombre,
      cargo: fila.cargo ?? '',
      area: fila.area ?? '',
      usuario: fila.usuario,
      estado: fila.estado === 'activo' ? 'activo' : 'pendiente',
      intentos: fila.intentos ?? 0,
    };
  }

  private async pedir(ruta: string, metodo = 'GET', cuerpo?: unknown): Promise<any> {
    let datos: any = null;
    try {
      const respuesta = await fetch(ruta, {
        method: metodo,
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...this.sesion.cabeceras(),
        },
        body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
      });
      if (respuesta.ok) {
        datos = await respuesta.json();
      }
    } catch {
      // Sin API queda lo que ya estaba cargado.
    }
    return datos;
  }
}
