import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';

interface Herramienta {
  nombre: string;
  permitida: boolean;
}

type AccionRegla = 'Bloquear' | 'Advertir' | 'Registrar';

interface ReglaDlp {
  nombre: string;
  descripcion: string;
  ejemplo: string;
  accion: AccionRegla;
  activa: boolean;
  fija: boolean;
}

interface Excepcion {
  alcance: string;
  tipo: 'Colaborador' | 'Perfil';
  detalle: string;
}

/** Configuración de políticas: tabs internos (herramientas, DLP, asignación). */
@Component({
  selector: 'app-politicas',
  standalone: true,
  imports: [CommonModule, FormsModule, TabsComponent, BadgeComponent],
  templateUrl: './politicas.component.html',
})
export class PoliticasComponent {
  readonly tabs: TabItem[] = [
    { id: 'herramientas', label: 'Herramientas y URLs' },
    { id: 'dlp', label: 'Reglas de DLP' },
    { id: 'asignacion', label: 'Asignación' },
  ];
  activeTab = 'herramientas';

  modoFlexible = false;

  herramientas: Herramienta[] = [
    { nombre: 'Claude', permitida: true },
    { nombre: 'ChatGPT', permitida: true },
    { nombre: 'Claude Code', permitida: true },
    { nombre: 'Codex', permitida: false },
    { nombre: 'Gemini', permitida: false },
    { nombre: 'GitHub Copilot', permitida: true },
  ];

  excepciones: Excepcion[] = [
    { alcance: 'Todas las IAs permitidas', tipo: 'Perfil', detalle: 'Equipo de I+D' },
    { alcance: 'Todas las IAs permitidas', tipo: 'Colaborador', detalle: 'Tobías Fuentes' },
  ];

  reglasDefault: ReglaDlp[] = [
    { nombre: 'API keys', descripcion: 'Detecta claves de API y tokens de acceso.', ejemplo: 'sk-live_51H8x... / AKIA4F3G2K1...', accion: 'Bloquear', activa: true, fija: true },
    { nombre: 'Credenciales', descripcion: 'Usuarios y contraseñas en texto plano.', ejemplo: 'usuario: admin, password: Vertice2024!', accion: 'Bloquear', activa: true, fija: true },
    { nombre: 'Bases de datos', descripcion: 'Cadenas de conexión y dumps de bases de datos.', ejemplo: 'postgres://user:pass@db.vertice.com:5432/prod', accion: 'Bloquear', activa: true, fija: true },
  ];

  reglasCustom: ReglaDlp[] = [
    { nombre: 'Estrategia de negocio', descripcion: 'No compartir información de estrategia de negocio.', ejemplo: '"Nuestro plan es adquirir a nuestro competidor en Q1..."', accion: 'Bloquear', activa: true, fija: false },
    { nombre: 'Campañas activas', descripcion: 'No mencionar campañas o eventos activos.', ejemplo: '"Lanzamos la campaña de Black Friday el día..."', accion: 'Advertir', activa: true, fija: false },
    { nombre: 'Lista de clientes', descripcion: 'No revelar la lista de clientes de la empresa.', ejemplo: '"Nuestros principales clientes son Acme, Globex..."', accion: 'Registrar', activa: false, fija: false },
  ];

  nuevaRegla = '';

  agregarRegla(): void {
    const texto = this.nuevaRegla.trim();
    if (!texto) return;
    this.reglasCustom = [
      { nombre: texto, descripcion: texto, ejemplo: 'Se generará automáticamente a partir de la descripción.', accion: 'Advertir', activa: true, fija: false },
      ...this.reglasCustom,
    ];
    this.nuevaRegla = '';
  }

  readonly areas = ['Marketing', 'Contabilidad', 'RR.HH.', 'Ingeniería', 'Legal'];
  readonly columnas = ['Claude', 'ChatGPT', 'Claude Code', 'DLP estricto', 'Modo flexible'];

  matriz: Record<string, boolean[]> = {
    Marketing: [true, true, false, false, true],
    Contabilidad: [true, false, false, true, false],
    'RR.HH.': [true, true, false, true, false],
    Ingeniería: [true, true, true, false, true],
    Legal: [true, false, false, true, false],
  };
}
