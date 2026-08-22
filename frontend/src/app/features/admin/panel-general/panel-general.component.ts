import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';
import { COLABORADORES } from '../../../shared/data/colaboradores';

interface Ranking {
  nombre: string;
  valor: number;
}

/** Panel general: dashboard agregado semanal con widgets de actividad DLP. */
@Component({
  selector: 'app-panel-general',
  standalone: true,
  imports: [CommonModule, RouterLink, StatTileComponent, BadgeComponent, AvatarStackComponent],
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

  // Solo quienes tienen algo que revisar esta semana: el directorio completo vive en /admin/colaboradores.
  readonly colaboradores = COLABORADORES.filter((c) => c.intentos > 0).sort((a, b) => b.intentos - a.intentos);

  max(lista: Ranking[]): number {
    return Math.max(...lista.map((x) => x.valor));
  }

  get pendientes(): number {
    return COLABORADORES.filter((c) => c.estado === 'pendiente').length;
  }
}
