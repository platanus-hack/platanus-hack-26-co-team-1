import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';

interface Ranking {
  nombre: string;
  valor: number;
}

interface ColaboradorResumen {
  id: string;
  nombre: string;
  area: string;
  estado: 'pendiente' | 'activo';
  intentos: number;
}

/** Panel general: dashboard agregado semanal con widgets de actividad DLP. */
@Component({
  selector: 'app-panel-general',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, StatTileComponent, BadgeComponent],
  templateUrl: './panel-general.component.html',
})
export class PanelGeneralComponent {
  rango = 'Esta semana';
  readonly rangos = ['Esta semana', 'Últimos 14 días', 'Este mes', 'Personalizado'];

  areasVulnerables: Ranking[] = [
    { nombre: 'Contabilidad', valor: 18 },
    { nombre: 'Ventas', valor: 12 },
    { nombre: 'Ingeniería', valor: 7 },
    { nombre: 'Marketing', valor: 4 },
  ];

  areasUsoIa: Ranking[] = [
    { nombre: 'Ingeniería', valor: 86 },
    { nombre: 'Marketing', valor: 61 },
    { nombre: 'Contabilidad', valor: 40 },
    { nombre: 'RR.HH.', valor: 22 },
  ];

  herramientas: Ranking[] = [
    { nombre: 'Claude', valor: 48 },
    { nombre: 'ChatGPT', valor: 33 },
    { nombre: 'Claude Code', valor: 14 },
    { nombre: 'Copilot', valor: 5 },
  ];

  colaboradores: ColaboradorResumen[] = [
    { id: '1', nombre: 'Marcos Iñiguez', area: 'Contabilidad', estado: 'activo', intentos: 9 },
    { id: '2', nombre: 'Renata Sotomayor', area: 'Marketing', estado: 'pendiente', intentos: 0 },
    { id: '3', nombre: 'Tobías Fuentes', area: 'Ingeniería', estado: 'activo', intentos: 2 },
    { id: '4', nombre: 'Camila Ordóñez', area: 'Contabilidad', estado: 'activo', intentos: 6 },
  ];

  max(lista: Ranking[]): number {
    return Math.max(...lista.map((x) => x.valor));
  }

  get pendientes(): number {
    return this.colaboradores.filter((c) => c.estado === 'pendiente').length;
  }
}
