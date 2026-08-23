import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { InsightItem, InsightsService } from '../../../shared/data/insights.service';

/**
 * La version completa de "Lectura de la semana": el card del panel general
 * muestra un adelanto, esto es todo. Vive en su propia pestana -y no en un
 * modal ni en un acordeon- porque una lectura pedagogica extensa compite mal
 * por espacio con los numeros del panel, y la idea es que se pueda leer con
 * calma, no de reojo.
 *
 * No trae su propio selector de rango: usa lo que ya eligio el panel general.
 * Si se entra directo (recarga de pagina, link compartido) no hay nada
 * cargado todavia, y ahi se pide sin rango -todo el historial- para no dejar
 * la pantalla vacia.
 */
@Component({
  selector: 'app-lectura-semana',
  standalone: true,
  imports: [CommonModule, RouterLink, BadgeComponent],
  templateUrl: './lectura-semana.component.html',
})
export class LecturaSemanaComponent implements OnInit {
  private readonly insightsSvc = inject(InsightsService);
  private readonly route = inject(ActivatedRoute);

  readonly resumen = this.insightsSvc.resumen;
  readonly cargando = this.insightsSvc.cargando;

  /** Etiqueta legible del rango que traia el link, si vino de un click en el panel. */
  rangoEtiqueta = '';

  ngOnInit(): void {
    const parametros = this.route.snapshot.queryParamMap;
    this.rangoEtiqueta = parametros.get('rango') ?? '';
    const desde = parametros.get('desde') ?? undefined;
    const hasta = parametros.get('hasta') ?? undefined;

    // Si ya hay algo cargado (se vino navegando desde el panel, mismo
    // servicio singleton) y el link no trae un rango distinto, no hace falta
    // repetir el pedido. Si no hay nada -o el link trae su propio rango-, se
    // pide de nuevo.
    if (!this.resumen() || desde || hasta) {
      void this.insightsSvc.cargar({ desde, hasta });
    }
  }

  readonly riesgos = () => (this.resumen()?.insights ?? []).filter((i) => i.tipo !== 'adopcion');
  readonly adopcion = () => (this.resumen()?.insights ?? []).filter((i) => i.tipo === 'adopcion');

  tono(i: InsightItem): BadgeTone {
    return i.tipo === 'riesgo' ? 'red' : 'accent';
  }
}
