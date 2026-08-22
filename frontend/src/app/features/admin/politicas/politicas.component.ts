import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { colorForName } from '../../../shared/utils/color-hash';

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
  tipo: 'Colaborador' | 'Perfil';
  detalle: string;
  /** Un colaborador o perfil puede acumular más de una regla propia. */
  alcances: string[];
}

/** Configuración de políticas: tabs internos (herramientas, DLP, asignación). */
@Component({
  selector: 'app-politicas',
  standalone: true,
  imports: [CommonModule, FormsModule, TabsComponent, BadgeComponent],
  templateUrl: './politicas.component.html',
})
export class PoliticasComponent {
  protected readonly colorForName = colorForName;

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

  // URLs que se cortan siempre, más allá de qué herramienta las sirva (ej. deepseek.com, grok.com).
  urlsBloqueadas: string[] = ['deepseek.com', 'grok.com'];
  nuevaUrlBloqueada = '';

  agregarUrlBloqueada(): void {
    const url = this.nuevaUrlBloqueada.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/$/, '');
    if (!url || this.urlsBloqueadas.includes(url)) return;
    this.urlsBloqueadas = [...this.urlsBloqueadas, url];
    this.nuevaUrlBloqueada = '';
  }

  quitarUrlBloqueada(url: string): void {
    this.urlsBloqueadas = this.urlsBloqueadas.filter((u) => u !== url);
  }

  excepciones: Excepcion[] = [
    { tipo: 'Perfil', detalle: 'Equipo de I+D', alcances: ['Todas las IAs permitidas'] },
    { tipo: 'Colaborador', detalle: 'Tobías Fuentes', alcances: ['Todas las IAs permitidas', 'Permitir Gemini'] },
  ];

  mostrarFormExcepcion = false;
  nuevaExcepcion: { tipo: 'Colaborador' | 'Perfil'; detalle: string; alcance: string } = {
    tipo: 'Colaborador',
    detalle: '',
    alcance: '',
  };

  get alcancesDisponibles(): string[] {
    const porHerramienta = this.herramientas.flatMap((h) => [`Permitir ${h.nombre}`, `Bloquear ${h.nombre}`]);
    return ['Todas las IAs permitidas', 'DLP estricto', 'Modo flexible', ...porHerramienta];
  }

  /** Si ya existe una excepción para ese colaborador/perfil, le suma la regla en vez de duplicar la tarjeta. */
  agregarExcepcion(): void {
    const detalle = this.nuevaExcepcion.detalle.trim();
    const alcance = this.nuevaExcepcion.alcance;
    if (!detalle || !alcance) return;

    const existente = this.excepciones.find((e) => e.tipo === this.nuevaExcepcion.tipo && e.detalle === detalle);
    if (existente) {
      if (!existente.alcances.includes(alcance)) existente.alcances = [...existente.alcances, alcance];
    } else {
      this.excepciones = [{ tipo: this.nuevaExcepcion.tipo, detalle, alcances: [alcance] }, ...this.excepciones];
    }

    this.nuevaExcepcion = { tipo: 'Colaborador', detalle: '', alcance: '' };
    this.mostrarFormExcepcion = false;
  }

  quitarExcepcion(excepcion: Excepcion): void {
    this.excepciones = this.excepciones.filter((e) => e !== excepcion);
  }

  quitarAlcance(excepcion: Excepcion, alcance: string): void {
    excepcion.alcances = excepcion.alcances.filter((a) => a !== alcance);
    if (excepcion.alcances.length === 0) this.quitarExcepcion(excepcion);
  }

  alternarCeldaMatriz(area: string, indice: number): void {
    const fila = this.matriz[area];
    fila[indice] = !fila[indice];
  }

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
