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
import { InsightsService } from '../../../shared/data/insights.service';

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
  readonly deEjemplo = this.metricas.deEjemplo;
  /** Lo que esta viendo el agente. Cae a la maqueta si no hay API. */
  readonly m = this.metricas.metricas;

  private readonly datos = inject(DirectorioService);

  private readonly insightsSvc = inject(InsightsService);
  readonly resumenPedagogico = this.insightsSvc.resumen;
  readonly cargandoInsights = this.insightsSvc.cargando;

  ngOnInit(): void {
    void this.cargarMetricas();
    void this.datos.cargarGente();
  }

  rango = 'Esta semana';
  readonly rangos = ['Esta semana', 'Últimos 14 días', 'Este mes', 'Personalizado'];

  // Fechas del rango personalizado, en el formato de <input type="date">
  // (yyyy-mm-dd). Precargadas con los ultimos 7 dias -y no vacias- para que
  // el "Aplicar" tenga un rango valido desde el primer click.
  personalizadoDesde = isoLocal(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000));
  personalizadoHasta = isoLocal(new Date());

  /** El botón cambia el filtro; "Personalizado" espera a que se confirme. */
  elegirRango(r: string): void {
    this.rango = r;
    if (r !== 'Personalizado') {
      void this.cargarMetricas();
    }
  }

  aplicarPersonalizado(): void {
    void this.cargarMetricas();
  }

  private async cargarMetricas(): Promise<void> {
    const limites = this.limitesDelRango();
    // En paralelo: son dos vistas distintas de la misma ventana, y ninguna
    // depende de que la otra termine primero.
    await Promise.all([this.metricas.cargar(limites), this.insightsSvc.cargar(limites)]);
  }

  /** El [desde, hasta] en ISO8601 UTC que le corresponde a `rango`. */
  private limitesDelRango(): { desde?: string; hasta?: string } {
    switch (this.rango) {
      case 'Esta semana':
        return { desde: this.haceDias(7) };
      case 'Últimos 14 días':
        return { desde: this.haceDias(14) };
      case 'Este mes': {
        const ahora = new Date();
        const inicio = Date.UTC(ahora.getUTCFullYear(), ahora.getUTCMonth(), 1);
        return { desde: new Date(inicio).toISOString() };
      }
      case 'Personalizado':
        return {
          desde: this.personalizadoDesde ? `${this.personalizadoDesde}T00:00:00.000Z` : undefined,
          hasta: this.personalizadoHasta ? `${this.personalizadoHasta}T23:59:59.999Z` : undefined,
        };
      default:
        return {};
    }
  }

  private haceDias(dias: number): string {
    const fecha = new Date();
    fecha.setUTCDate(fecha.getUTCDate() - dias);
    return fecha.toISOString();
  }

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

  /** Riesgo llama la atencion; adopcion es informativo, no una alarma. */
  tonoInsight(tipo: string | undefined): BadgeTone {
    return tipo === 'riesgo' ? 'red' : 'accent';
  }

  // El card de aca es un adelanto, no la lectura entera: cuando hay mas de
  // dos items por columna, el resto vive en /admin/lectura, mejor organizado
  // por tipo en vez de compitiendo por espacio con los numeros del panel.
  private readonly TEASER = 2;

  get insightsTeaser() {
    return (this.resumenPedagogico()?.insights ?? []).slice(0, this.TEASER);
  }

  get estrategiasTeaser() {
    return (this.resumenPedagogico()?.estrategias ?? []).slice(0, this.TEASER);
  }

  /** Cuanto quedo afuera del adelanto. 0 esconde el link a "ver todo". */
  get observacionesRestantes(): number {
    const r = this.resumenPedagogico();
    return r
      ? Math.max(0, r.insights.length - this.TEASER) + Math.max(0, r.estrategias.length - this.TEASER)
      : 0;
  }

  /** El rango activo, para que /admin/lectura muestre lo mismo que este panel. */
  get queryParamsLectura(): Record<string, string> {
    const limites = this.limitesDelRango();
    const parametros: Record<string, string> = { rango: this.rango };
    if (limites.desde) parametros['desde'] = limites.desde;
    if (limites.hasta) parametros['hasta'] = limites.hasta;
    return parametros;
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
