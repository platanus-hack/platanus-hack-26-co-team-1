import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';
import { EstadoColaborador } from '../../../shared/data/colaboradores';
import { DirectorioService } from '../../../shared/data/directorio.service';

interface NuevoColaborador {
  nombre: string;
  cargo: string;
  area: string;
  usuario: string;
  estado: EstadoColaborador;
}

interface FilaBulk extends NuevoColaborador {
  fila: number;
  error?: string;
}

/**
 * Colaboradores: directorio (buscar y ver a todo el equipo) separado del
 * alta de cuentas nuevas (individual o carga masiva por CSV): son dos
 * tareas distintas y no deberían competir por la misma pantalla.
 */
@Component({
  selector: 'app-colaboradores',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, TabsComponent, BadgeComponent, AvatarStackComponent],
  templateUrl: './colaboradores.component.html',
})
export class ColaboradoresComponent implements OnInit {
  private readonly datos = inject(DirectorioService);

  /** La gente de verdad. Cae a la maqueta si el API no responde. */
  readonly gente = this.datos.gente;

  ngOnInit(): void {
    void this.datos.cargarGente();
  }

  readonly tabs: TabItem[] = [
    { id: 'directorio', label: 'Directorio' },
    { id: 'individual', label: 'Alta individual' },
    { id: 'bulk', label: 'Carga masiva' },
  ];
  activeTab = 'directorio';

  readonly areas = ['Marketing', 'Contabilidad', 'RR.HH.', 'Ingeniería', 'Legal'];

  // --- Directorio: buscar y filtrar a todo el equipo ya dado de alta. ---
  busqueda = '';
  filtroArea = 'Todas';
  filtroEstado: 'Todos' | EstadoColaborador = 'Todos';

  get directorioFiltrado() {
    const q = this.busqueda.trim().toLowerCase();
    return this.gente().filter((c) => {
      const coincideNombre = !q || c.nombre.toLowerCase().includes(q) || c.cargo.toLowerCase().includes(q);
      const coincideArea = this.filtroArea === 'Todas' || c.area === this.filtroArea;
      const coincideEstado = this.filtroEstado === 'Todos' || c.estado === this.filtroEstado;
      return coincideNombre && coincideArea && coincideEstado;
    });
  }

  // --- Alta individual: un formulario, una tabla de lo agregado en esta sesión. ---
  form: NuevoColaborador = { nombre: '', cargo: '', area: '', usuario: '', estado: 'pendiente' };

  agregadosRecientemente: NuevoColaborador[] = [];

  async agregarColaborador(): Promise<void> {
    // Nombre y usuario son lo mínimo, y el backend valida lo mismo: sin usuario
    // la persona no se puede cruzar con ningún evento.
    if (this.form.nombre && this.form.usuario) {
      const nuevo = { ...this.form, estado: 'pendiente' as EstadoColaborador };
      await this.datos.guardar([nuevo]);
      this.agregadosRecientemente = [nuevo, ...this.agregadosRecientemente];
      this.form = { nombre: '', cargo: '', area: '', usuario: '', estado: 'pendiente' };
    }
  }

  // --- Carga masiva: previsualización de un CSV antes de confirmar la importación. ---
  archivoNombre = '';
  filasBulk: FilaBulk[] = [];

  /** Lee el CSV de verdad y lo previsualiza. Nada se guarda hasta confirmar. */
  async leerArchivo(evento: Event): Promise<void> {
    const entrada = evento.target as HTMLInputElement;
    const archivo = entrada.files?.[0];
    if (archivo) {
      this.archivoNombre = archivo.name;
      this.filasBulk = this.parsear(await archivo.text());
    }
  }

  /**
   * CSV mínimo: `nombre,cargo,area,usuario`, con o sin encabezado.
   *
   * Se valida acá **y** en el backend. Acá para que quien sube el archivo vea
   * qué fila está mal antes de confirmar; allá porque esta validación corre en
   * el navegador y cualquiera la puede saltar.
   */
  private parsear(texto: string): FilaBulk[] {
    // Se parte por salto de línea y se limpia el retorno de carro aparte: un
    // CSV exportado desde Excel en Windows trae CRLF, y sin esto el último
    // campo de cada fila se queda con un \r pegado que rompe la comparación.
    const lineas = texto.split('\n').filter((l) => l.trim());
    const filas: FilaBulk[] = [];

    lineas.forEach((linea, indice) => {
      const [nombre = '', cargo = '', area = '', usuario = ''] = linea
        .split(',')
        .map((c) => c.trim());

      const esEncabezado = indice === 0 && nombre.toLowerCase() === 'nombre';
      if (!esEncabezado) {
        let error: string | undefined;
        if (!nombre) {
          error = 'Falta el nombre';
        } else if (!usuario) {
          error = 'Falta el usuario';
        } else if (area && !this.areas.includes(area)) {
          error = `Área "${area}" no existe`;
        }
        filas.push({ fila: indice + 1, nombre, cargo, area, usuario, estado: 'pendiente', error });
      }
    });
    return filas;
  }

  /** Sube solo las válidas: una fila rota no puede cancelar a las otras. */
  async confirmarCarga(): Promise<void> {
    const buenas = this.filasBulk.filter((f) => !f.error);
    if (buenas.length) {
      await this.datos.guardar(buenas);
      this.quitarArchivo();
    }
  }

  quitarArchivo(): void {
    this.archivoNombre = '';
    this.filasBulk = [];
  }

  get filasValidas(): number {
    return this.filasBulk.filter((f) => !f.error).length;
  }
}
