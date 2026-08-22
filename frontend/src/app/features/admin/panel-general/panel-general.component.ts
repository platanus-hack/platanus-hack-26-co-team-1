import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';
import { COLABORADORES } from '../../../shared/data/colaboradores';
// `Ranking` sale del servicio y no se declara aca: las dos ramas lo definieron
// por su cuenta con la misma forma, y dos definiciones de lo mismo se separan
// en cuanto una de las dos cambie.
import { MetricasService, Ranking } from '../../../shared/data/metricas.service';

/** Panel general: dashboard agregado semanal con widgets de actividad DLP. */
@Component({
  selector: 'app-panel-general',
  standalone: true,
  imports: [CommonModule, RouterLink, StatTileComponent, BadgeComponent, AvatarStackComponent],
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

  // Solo quienes tienen algo que revisar esta semana: el directorio completo vive en /admin/colaboradores.
  readonly colaboradores = COLABORADORES.filter((c) => c.intentos > 0).sort((a, b) => b.intentos - a.intentos);

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
    return COLABORADORES.filter((c) => c.estado === 'pendiente').length;
  }
}
