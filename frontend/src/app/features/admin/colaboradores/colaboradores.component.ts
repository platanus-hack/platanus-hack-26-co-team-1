import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';
import { COLABORADORES, EstadoColaborador } from '../../../shared/data/colaboradores';

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
export class ColaboradoresComponent {
  readonly tabs: TabItem[] = [
    { id: 'directorio', label: 'Directorio' },
    { id: 'individual', label: 'Alta individual' },
    { id: 'bulk', label: 'Carga masiva' },
  ];
  activeTab = 'directorio';

  readonly areas = ['Marketing', 'Contabilidad', 'RR.HH.', 'Ingeniería', 'Legal'];

  // --- Directorio: buscar y filtrar a todo el equipo ya dado de alta. ---
  readonly directorio = COLABORADORES;
  busqueda = '';
  filtroArea = 'Todas';
  filtroEstado: 'Todos' | EstadoColaborador = 'Todos';

  get directorioFiltrado() {
    const q = this.busqueda.trim().toLowerCase();
    return this.directorio.filter((c) => {
      const coincideNombre = !q || c.nombre.toLowerCase().includes(q) || c.cargo.toLowerCase().includes(q);
      const coincideArea = this.filtroArea === 'Todas' || c.area === this.filtroArea;
      const coincideEstado = this.filtroEstado === 'Todos' || c.estado === this.filtroEstado;
      return coincideNombre && coincideArea && coincideEstado;
    });
  }

  // --- Alta individual: un formulario, una tabla de lo agregado en esta sesión. ---
  form: NuevoColaborador = { nombre: '', cargo: '', area: '', usuario: '', estado: 'pendiente' };

  agregadosRecientemente: NuevoColaborador[] = [
    { nombre: 'Marcos Iñiguez', cargo: 'Analista financiero', area: 'Contabilidad', usuario: 'miniguez', estado: 'activo' },
    { nombre: 'Renata Sotomayor', cargo: 'Diseñadora de producto', area: 'Marketing', usuario: 'rsotomayor', estado: 'pendiente' },
    { nombre: 'Tobías Fuentes', cargo: 'Backend engineer', area: 'Ingeniería', usuario: 'tfuentes', estado: 'activo' },
  ];

  agregarColaborador(): void {
    if (!this.form.nombre || !this.form.usuario) return;
    this.agregadosRecientemente = [{ ...this.form, estado: 'pendiente' }, ...this.agregadosRecientemente];
    this.form = { nombre: '', cargo: '', area: '', usuario: '', estado: 'pendiente' };
  }

  // --- Carga masiva: previsualización de un CSV antes de confirmar la importación. ---
  archivoNombre = '';
  filasBulk: FilaBulk[] = [];

  simularCarga(): void {
    this.archivoNombre = 'colaboradores_q3.csv';
    this.filasBulk = [
      { fila: 2, nombre: 'Valentina Rojas', cargo: 'Frontend engineer', area: 'Ingeniería', usuario: 'vrojas', estado: 'pendiente' },
      { fila: 3, nombre: 'Joaquín Herrera', cargo: 'DevOps engineer', area: 'Ingeniería', usuario: 'jherrera', estado: 'pendiente' },
      { fila: 4, nombre: '', cargo: 'Soporte TI', area: 'Ingeniería', usuario: 'jsalas', estado: 'pendiente', error: 'Falta el nombre' },
      { fila: 5, nombre: 'Fernanda Lagos', cargo: 'Abogada corporativa', area: 'Ventas', usuario: 'flagos', estado: 'pendiente', error: 'Área "Ventas" no existe' },
    ];
  }

  quitarArchivo(): void {
    this.archivoNombre = '';
    this.filasBulk = [];
  }

  get filasValidas(): number {
    return this.filasBulk.filter((f) => !f.error).length;
  }
}
