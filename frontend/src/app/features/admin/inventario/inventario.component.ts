import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { StatTileComponent } from '../../../shared/ui/stat-tile/stat-tile.component';
import { AvatarStackComponent } from '../../../shared/ui/avatar-stack/avatar-stack.component';

type EstadoAgente = 'aprobado' | 'no-catalogado' | 'no-aprobado';

interface Agente {
  nombre: string;
  tipo: 'CLI' | 'IDE' | 'Escritorio' | 'Navegador';
  colaboradores: string[];
  ultimaActividad: string;
  estado: EstadoAgente;
}

interface ServidorMcp {
  nombre: string;
  agentes: string[];
  alcance: string;
  colaboradores: string[];
  estado: EstadoAgente;
}

interface Skill {
  nombre: string;
  agente: string;
  colaboradores: string[];
  estado: EstadoAgente;
}

const TONE_POR_ESTADO: Record<EstadoAgente, BadgeTone> = {
  aprobado: 'green',
  'no-catalogado': 'amber',
  'no-aprobado': 'red',
};

const LABEL_POR_ESTADO: Record<EstadoAgente, string> = {
  aprobado: 'Aprobado',
  'no-catalogado': 'Sin catalogar',
  'no-aprobado': 'No aprobado',
};

/**
 * Agent Inventory: descubrimiento de agentes de IA, servidores MCP y skills
 * en uso a través de toda la flota (el mismo principio que "Shadow AI
 * descubierta" del panel de eventos, pero mapeando la superficie completa:
 * qué corre, no solo qué se bloqueó).
 */
@Component({
  selector: 'app-inventario',
  standalone: true,
  imports: [CommonModule, BadgeComponent, StatTileComponent, AvatarStackComponent],
  templateUrl: './inventario.component.html',
})
export class InventarioComponent {
  toneDe(estado: EstadoAgente): BadgeTone {
    return TONE_POR_ESTADO[estado];
  }

  labelDe(estado: EstadoAgente): string {
    return LABEL_POR_ESTADO[estado];
  }

  readonly agentes: Agente[] = [
    {
      nombre: 'Claude Code',
      tipo: 'CLI',
      colaboradores: ['Tobías Fuentes', 'Marcos Iñiguez', 'Ismael Vega', 'Valentina Rojas', 'Joaquín Herrera', 'Fernanda Lagos'],
      ultimaActividad: 'Hace 12 min',
      estado: 'aprobado',
    },
    {
      nombre: 'GitHub Copilot',
      tipo: 'IDE',
      colaboradores: ['Tobías Fuentes', 'Cristóbal Muñoz', 'Ismael Vega', 'Joaquín Herrera', 'Marcos Iñiguez'],
      ultimaActividad: 'Hace 4 min',
      estado: 'aprobado',
    },
    {
      nombre: 'Cursor',
      tipo: 'IDE',
      colaboradores: ['Cristóbal Muñoz', 'Valentina Rojas', 'Tobías Fuentes'],
      ultimaActividad: 'Hace 31 min',
      estado: 'aprobado',
    },
    {
      nombre: 'ChatGPT Desktop',
      tipo: 'Escritorio',
      colaboradores: ['Renata Sotomayor', 'Camila Ordóñez', 'Bárbara Concha'],
      ultimaActividad: 'Hace 2 h',
      estado: 'no-catalogado',
    },
    {
      nombre: 'Windsurf',
      tipo: 'IDE',
      colaboradores: ['Ismael Vega', 'Fernanda Lagos'],
      ultimaActividad: 'Hace 5 h',
      estado: 'no-catalogado',
    },
    {
      nombre: 'Gemini CLI',
      tipo: 'CLI',
      colaboradores: ['Cristóbal Muñoz'],
      ultimaActividad: 'Ayer',
      estado: 'no-aprobado',
    },
  ];

  readonly servidoresMcp: ServidorMcp[] = [
    {
      nombre: 'filesystem',
      agentes: ['Claude Code', 'Cursor'],
      alcance: 'Lectura/escritura del repo local',
      colaboradores: ['Tobías Fuentes', 'Marcos Iñiguez', 'Cristóbal Muñoz', 'Valentina Rojas', 'Ismael Vega'],
      estado: 'aprobado',
    },
    {
      nombre: 'github',
      agentes: ['Claude Code', 'GitHub Copilot'],
      alcance: 'Issues, PRs y contenido de repos',
      colaboradores: ['Tobías Fuentes', 'Marcos Iñiguez', 'Ismael Vega', 'Joaquín Herrera', 'Cristóbal Muñoz', 'Fernanda Lagos'],
      estado: 'aprobado',
    },
    {
      nombre: 'postgres-prod',
      agentes: ['Cursor'],
      alcance: 'Lectura directa sobre la base de producción',
      colaboradores: ['Cristóbal Muñoz', 'Valentina Rojas'],
      estado: 'no-catalogado',
    },
    {
      nombre: 'slack',
      agentes: ['Claude Code'],
      alcance: 'Leer y publicar en canales internos',
      colaboradores: ['Tobías Fuentes', 'Renata Sotomayor'],
      estado: 'no-catalogado',
    },
    {
      nombre: 'browser-automation',
      agentes: ['Windsurf'],
      alcance: 'Control de navegador sin sandbox',
      colaboradores: ['Ismael Vega'],
      estado: 'no-aprobado',
    },
  ];

  readonly skills: Skill[] = [
    { nombre: 'code-review', agente: 'Claude Code', colaboradores: ['Tobías Fuentes', 'Marcos Iñiguez', 'Ismael Vega'], estado: 'aprobado' },
    { nombre: 'web-search', agente: 'ChatGPT Desktop', colaboradores: ['Renata Sotomayor', 'Camila Ordóñez'], estado: 'aprobado' },
    { nombre: 'sql-query', agente: 'Cursor', colaboradores: ['Cristóbal Muñoz'], estado: 'no-catalogado' },
    { nombre: 'send-email', agente: 'Windsurf', colaboradores: ['Ismael Vega'], estado: 'no-aprobado' },
    { nombre: 'pdf-export', agente: 'GitHub Copilot', colaboradores: ['Fernanda Lagos', 'Joaquín Herrera'], estado: 'aprobado' },
  ];

  get totalAgentes(): number {
    return this.agentes.length;
  }

  get totalMcp(): number {
    return this.servidoresMcp.length;
  }

  get totalSkills(): number {
    return this.skills.length;
  }

  get totalSinAprobar(): number {
    const items = [...this.agentes, ...this.servidoresMcp, ...this.skills];
    return items.filter((i) => i.estado !== 'aprobado').length;
  }
}
