import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { ActividadService, EntradaActividad } from '../../../shared/data/actividad.service';
import { nombreDeRegla, NOMBRE_DE_PROCESO } from '../../../shared/data/metricas.service';
import { SesionService } from '../../../shared/data/sesion.service';

/** Los tres grupos que ve la persona; el contrato del agente distingue cuatro
 * acciones (`blocked`, `redacted`, `warned`, `allowed`) porque el motor
 * necesita esa precisión, pero acá `blocked` y `redacted` cuentan igual: las
 * dos son "esto no salió". */
type AccionTab = 'todos' | 'blocked' | 'warned' | 'allowed';

const ETIQUETA_ACCION: Record<string, { label: string; tone: BadgeTone; grupo: AccionTab }> = {
  blocked: { label: 'Bloqueado', tone: 'red', grupo: 'blocked' },
  redacted: { label: 'Bloqueado', tone: 'red', grupo: 'blocked' },
  warned: { label: 'Advertido', tone: 'amber', grupo: 'warned' },
  allowed: { label: 'Permitido', tone: 'neutral', grupo: 'allowed' },
};

/** "Mi actividad": el propio colaborador ve sus intentos y el porqué, en tono pedagógico. */
@Component({
  selector: 'app-actividad',
  standalone: true,
  imports: [CommonModule, RouterLink, BadgeComponent, LogoComponent, TabsComponent],
  templateUrl: './actividad.component.html',
})
export class ActividadComponent implements OnInit {
  private readonly servicio = inject(ActividadService);
  protected readonly sesionSvc = inject(SesionService);

  readonly cargando = this.servicio.cargando;
  readonly cargada = this.servicio.cargada;

  ngOnInit(): void {
    void this.servicio.cargar();
  }

  readonly tabs: TabItem[] = [
    { id: 'todos', label: 'Todos' },
    { id: 'blocked', label: 'Bloqueados' },
    { id: 'warned', label: 'Advertidos' },
    { id: 'allowed', label: 'Con log' },
  ];
  activeTab = 'todos';

  get filtradas(): EntradaActividad[] {
    const todas = this.servicio.entradas();
    return this.activeTab === 'todos'
      ? todas
      : todas.filter((e) => this.grupoDe(e.action) === this.activeTab);
  }

  private grupoDe(action: string): AccionTab {
    return ETIQUETA_ACCION[action]?.grupo ?? 'allowed';
  }

  etiqueta(action: string): string {
    return ETIQUETA_ACCION[action]?.label ?? action;
  }

  tone(action: string): BadgeTone {
    return ETIQUETA_ACCION[action]?.tone ?? 'neutral';
  }

  herramienta(e: EntradaActividad): string {
    return (e.process && NOMBRE_DE_PROCESO[e.process]) || e.process || 'Sin atribuir';
  }

  motivo(e: EntradaActividad): string {
    return e.rule_id ? nombreDeRegla(e.rule_id) : 'Sin detección específica';
  }

  fecha(iso: string): string {
    const fecha = new Date(iso);
    if (Number.isNaN(fecha.getTime())) return iso;
    return fecha.toLocaleString('es', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  salir(): void {
    this.sesionSvc.salir();
  }
}
