import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';

interface Intento {
  fecha: string;
  herramienta: string;
  regla: string;
  accion: 'Bloqueado' | 'Advertido' | 'Registrado';
}

interface ColaboradorDetalle {
  nombre: string;
  cargo: string;
  area: string;
  instaladoDesde: string;
  herramientas: { nombre: string; porcentaje: number }[];
  temas: string[];
  intentos: Intento[];
  estrategiaSugerida?: string;
}

const DATA: Record<string, ColaboradorDetalle> = {
  '1': {
    nombre: 'Marcos Iñiguez',
    cargo: 'Analista financiero',
    area: 'Contabilidad',
    instaladoDesde: '3 de marzo, 2026',
    herramientas: [
      { nombre: 'ChatGPT', porcentaje: 64 },
      { nombre: 'Claude', porcentaje: 36 },
    ],
    temas: ['Análisis de datos', 'Reportería financiera', 'Redacción de correos'],
    intentos: [
      { fecha: '20 ago, 2026', herramienta: 'ChatGPT', regla: 'API keys', accion: 'Bloqueado' },
      { fecha: '18 ago, 2026', herramienta: 'ChatGPT', regla: 'Bases de datos', accion: 'Bloqueado' },
      { fecha: '12 ago, 2026', herramienta: 'Claude', regla: 'Lista de clientes', accion: 'Advertido' },
      { fecha: '05 ago, 2026', herramienta: 'ChatGPT', regla: 'Credenciales', accion: 'Bloqueado' },
    ],
    estrategiaSugerida: 'Marcos reincide en compartir credenciales y claves de API en sus consultas (3 veces en las últimas dos semanas). Se recomienda una capacitación breve sobre manejo seguro de credenciales.',
  },
  '2': {
    nombre: 'Renata Sotomayor',
    cargo: 'Diseñadora de producto',
    area: 'Marketing',
    instaladoDesde: 'Aún no instala la app',
    herramientas: [],
    temas: [],
    intentos: [],
  },
  '3': {
    nombre: 'Tobías Fuentes',
    cargo: 'Backend engineer',
    area: 'Ingeniería',
    instaladoDesde: '11 de enero, 2026',
    herramientas: [
      { nombre: 'Claude Code', porcentaje: 58 },
      { nombre: 'Claude', porcentaje: 30 },
      { nombre: 'Copilot', porcentaje: 12 },
    ],
    temas: ['Código fuente', 'Debugging', 'Arquitectura de sistemas'],
    intentos: [
      { fecha: '15 ago, 2026', herramienta: 'Claude Code', regla: 'Bases de datos', accion: 'Registrado' },
      { fecha: '02 ago, 2026', herramienta: 'Claude', regla: 'Estrategia de negocio', accion: 'Advertido' },
    ],
  },
  '4': {
    nombre: 'Camila Ordóñez',
    cargo: 'Contadora senior',
    area: 'Contabilidad',
    instaladoDesde: '28 de julio, 2026',
    herramientas: [
      { nombre: 'ChatGPT', porcentaje: 80 },
      { nombre: 'Claude', porcentaje: 20 },
    ],
    temas: ['Reportería financiera', 'Análisis de datos'],
    intentos: [
      { fecha: '19 ago, 2026', herramienta: 'ChatGPT', regla: 'Credenciales', accion: 'Bloqueado' },
      { fecha: '10 ago, 2026', herramienta: 'ChatGPT', regla: 'Campañas activas', accion: 'Advertido' },
    ],
  },
};

/** Vista de detalle de un colaborador, accedida desde el panel general. */
@Component({
  selector: 'app-panel-colaborador',
  standalone: true,
  imports: [CommonModule, RouterLink, BadgeComponent],
  templateUrl: './panel-colaborador.component.html',
})
export class PanelColaboradorComponent {
  colaborador: ColaboradorDetalle;

  constructor(route: ActivatedRoute) {
    const id = route.snapshot.paramMap.get('id') ?? '1';
    this.colaborador = DATA[id] ?? DATA['1'];
  }

  get bloqueados(): number {
    return this.colaborador.intentos.filter((i) => i.accion === 'Bloqueado').length;
  }

  tone(accion: Intento['accion']): BadgeTone {
    if (accion === 'Bloqueado') return 'red';
    if (accion === 'Advertido') return 'amber';
    return 'neutral';
  }
}
