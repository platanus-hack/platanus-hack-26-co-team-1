import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { MetricasService, Ranking } from '../../../shared/data/metricas.service';

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
export class PanelGeneralComponent implements OnInit {
  private readonly metricas = inject(MetricasService);
  /** Lo que esta viendo el agente. Cae a la maqueta si no hay API. */
  readonly m = this.metricas.metricas;

  ngOnInit(): void {
    void this.metricas.cargar();
  }

  rango = 'Esta semana';
  readonly rangos = ['Esta semana', 'Últimos 14 días', 'Este mes', 'Personalizado'];

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
    // Sin el 1, una lista vacia da -Infinity y las barras quedan en NaN.
    return Math.max(1, ...lista.map((x) => x.valor));
  }

  /** Un destino aprobado no preocupa; uno que nadie clasifico, si. */
  tonoDestino(clasificacion: string): BadgeTone {
    const tonos: Record<string, BadgeTone> = {
      ai_approved: 'green',
      ai_unapproved: 'red',
      ai_unknown: 'amber',
    };
    return tonos[clasificacion] ?? 'neutral';
  }

  etiquetaDestino(clasificacion: string): string {
    const etiquetas: Record<string, string> = {
      ai_approved: 'aprobada',
      ai_unapproved: 'sin aprobar',
      ai_unknown: 'sin clasificar',
    };
    return etiquetas[clasificacion] ?? clasificacion;
  }

  get pendientes(): number {
    return this.colaboradores.filter((c) => c.estado === 'pendiente').length;
  }
}
