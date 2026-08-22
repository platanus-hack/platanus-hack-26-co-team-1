import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';

interface Colaborador {
  nombre: string;
  cargo: string;
  area: string;
  usuario: string;
  estado: 'pendiente' | 'activo';
}

interface FilaBulk extends Colaborador {
  fila: number;
  error?: string;
}

/** Alta de colaboradores: modo individual y modo bulk (CSV) en una misma pantalla. */
@Component({
  selector: 'app-colaboradores',
  standalone: true,
  imports: [CommonModule, FormsModule, TabsComponent, BadgeComponent],
  templateUrl: './colaboradores.component.html',
})
export class ColaboradoresComponent {
  readonly tabs: TabItem[] = [
    { id: 'individual', label: 'Individual' },
    { id: 'bulk', label: 'Carga masiva' },
  ];
  activeTab = 'individual';

  readonly areas = ['Marketing', 'Contabilidad', 'RR.HH.', 'Ingeniería', 'Legal'];

  form = { nombre: '', cargo: '', area: '', usuario: '', password: '' };

  colaboradores: Colaborador[] = [
    { nombre: 'Marcos Iñiguez', cargo: 'Analista financiero', area: 'Contabilidad', usuario: 'miniguez', estado: 'activo' },
    { nombre: 'Renata Sotomayor', cargo: 'Diseñadora de producto', area: 'Marketing', usuario: 'rsotomayor', estado: 'pendiente' },
    { nombre: 'Tobías Fuentes', cargo: 'Backend engineer', area: 'Ingeniería', usuario: 'tfuentes', estado: 'activo' },
  ];

  agregarColaborador(): void {
    if (!this.form.nombre || !this.form.usuario) return;
    this.colaboradores = [
      { nombre: this.form.nombre, cargo: this.form.cargo, area: this.form.area, usuario: this.form.usuario, estado: 'pendiente' },
      ...this.colaboradores,
    ];
    this.form = { nombre: '', cargo: '', area: '', usuario: '', password: '' };
  }

  archivoNombre = '';
  filasBulk: FilaBulk[] = [];

  simularCarga(): void {
    this.archivoNombre = 'colaboradores_q3.csv';
    this.filasBulk = [
      { fila: 2, nombre: 'Camila Ordóñez', cargo: 'Contadora senior', area: 'Contabilidad', usuario: 'cordonez', estado: 'pendiente' },
      { fila: 3, nombre: 'Ismael Vega', cargo: 'Growth marketer', area: 'Marketing', usuario: 'ivega', estado: 'pendiente' },
      { fila: 4, nombre: '', cargo: 'Soporte TI', area: 'Ingeniería', usuario: 'jsalas', estado: 'pendiente', error: 'Falta el nombre' },
      { fila: 5, nombre: 'Bárbara Concha', cargo: 'Reclutadora', area: 'Ventas', usuario: 'bconcha', estado: 'pendiente', error: 'Área "Ventas" no existe' },
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
