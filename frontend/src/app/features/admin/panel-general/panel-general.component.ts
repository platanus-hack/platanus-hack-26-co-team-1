import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';
import { DirectorioService } from '../../../shared/data/directorio.service';
// `Ranking` sale del servicio y no se declara aca: las dos ramas lo definieron
// por su cuenta con la misma forma, y dos definiciones de lo mismo se separan
// en cuanto una de las dos cambie.
import { MetricasService, Ranking } from '../../../shared/data/metricas.service';

/** Fecha local en formato YYYY-MM-DD, para precargar los <input type="date">. */
function isoLocal(d: Date): string {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 10);
}

/** Panel general: dashboard agregado semanal con widgets de actividad DLP. */
@Component({
  selector: 'app-panel-general',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, StatTileComponent, BadgeComponent, AvatarStackComponent],
  templateUrl: './panel-general.component.html',
})
export class PanelGeneralComponent implements OnInit {
  private readonly metricas = inject(MetricasService);
  /** Lo que esta viendo el agente. Cae a la maqueta si no hay API. */
  readonly m = this.metricas.metricas;

  private readonly datos = inject(DirectorioService);

  ngOnInit(): void {
    void this.metricas.cargar();
    void this.datos.cargarGente();
  }

  rango = 'Esta semana';
  readonly rangos = ['Esta semana', 'Últimos 14 días', 'Este mes', 'Personalizado'];

  // Rango personalizado: por defecto, los ultimos 7 dias.
  desde = isoLocal(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000));
  hasta = isoLocal(new Date());

  // Solo quienes tienen algo que revisar esta semana: el directorio completo
  // vive en /admin/colaboradores. Los intentos los cuenta el backend cruzando
  // el seudonimo del evento con el directorio.
  get colaboradores() {
    return this.datos
      .gente()
      .filter((c) => c.intentos > 0)
      .sort((a, b) => b.intentos - a.intentos);
  }

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
    return this.datos.gente().filter((c) => c.estado === 'pendiente').length;
  }
}
