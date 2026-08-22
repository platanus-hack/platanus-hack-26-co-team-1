import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { BadgeComponent, BadgeTone } from '../../../shared/ui/badge/badge.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';

type Accion = 'Bloqueado' | 'Advertido' | 'Permitido';

interface EntradaActividad {
  fecha: string;
  herramienta: string;
  accion: Accion;
  motivo: string;
  explicacion: string;
}

/** "Mi actividad": el propio colaborador ve sus intentos y el porqué, en tono pedagógico. */
@Component({
  selector: 'app-actividad',
  standalone: true,
  imports: [CommonModule, RouterLink, BadgeComponent, LogoComponent, TabsComponent],
  templateUrl: './actividad.component.html',
})
export class ActividadComponent {
  readonly tabs: TabItem[] = [
    { id: 'todos', label: 'Todos' },
    { id: 'Bloqueado', label: 'Bloqueados' },
    { id: 'Advertido', label: 'Advertidos' },
    { id: 'Permitido', label: 'Con log' },
  ];
  activeTab = 'todos';

  readonly temas = ['Reportería financiera', 'Análisis de datos', 'Redacción de correos'];

  readonly entradas: EntradaActividad[] = [
    {
      fecha: '20 ago, 2026 · 11:42',
      herramienta: 'ChatGPT',
      accion: 'Bloqueado',
      motivo: 'API keys',
      explicacion: 'El mensaje incluía una clave de API activa. Estas claves dan acceso directo a sistemas de la empresa (si se filtran, cualquiera con esa clave puede actuar como si fuera el servicio, sin que quede un registro fácil de rastrear).',
    },
    {
      fecha: '18 ago, 2026 · 09:15',
      herramienta: 'ChatGPT',
      accion: 'Bloqueado',
      motivo: 'Bases de datos',
      explicacion: 'Se detectó una cadena de conexión a una base de datos de producción. Compartirla, aunque sea sin intención, expone credenciales y la ubicación exacta de datos sensibles de clientes.',
    },
    {
      fecha: '12 ago, 2026 · 16:03',
      herramienta: 'Claude',
      accion: 'Advertido',
      motivo: 'Lista de clientes',
      explicacion: 'Mencionaste nombres de clientes en tu consulta. No se bloqueó porque el contexto parecía interno, pero esta información es confidencial (evita incluir nombres reales al pedir ayuda a una IA externa).',
    },
    {
      fecha: '05 ago, 2026 · 14:30',
      herramienta: 'ChatGPT',
      accion: 'Bloqueado',
      motivo: 'Credenciales',
      explicacion: 'El texto incluía un usuario y contraseña en texto plano. Aunque sea de un ambiente de prueba, compartir credenciales entrena a la IA con datos que no deberían salir de la empresa.',
    },
    {
      fecha: '01 ago, 2026 · 10:12',
      herramienta: 'Claude Code',
      accion: 'Permitido',
      motivo: 'Código fuente (con log)',
      explicacion: 'Compartiste un fragmento de código interno. No disparó ninguna regla de bloqueo, pero queda registrado porque tu área maneja código propietario (es solo un registro, no una advertencia).',
    },
  ];

  get filtradas(): EntradaActividad[] {
    if (this.activeTab === 'todos') return this.entradas;
    return this.entradas.filter((e) => e.accion === this.activeTab);
  }

  tone(accion: Accion): BadgeTone {
    if (accion === 'Bloqueado') return 'red';
    if (accion === 'Advertido') return 'amber';
    return 'neutral';
  }
}
