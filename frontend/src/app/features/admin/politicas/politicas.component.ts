import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TabsComponent, TabItem } from '../../../shared/ui/tabs/tabs.component';
import { BadgeComponent } from '../../../shared/ui/badge/badge.component';
import { colorForName } from '../../../shared/utils/color-hash';
import { PoliticaService, ReglaPersonalizada } from '../../../shared/data/politica.service';
import { DirectorioService } from '../../../shared/data/directorio.service';

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

/** Configuración de políticas: tabs internos (herramientas, DLP, diccionario, detección). */
@Component({
  selector: 'app-politicas',
  standalone: true,
  imports: [CommonModule, FormsModule, TabsComponent, BadgeComponent],
  templateUrl: './politicas.component.html',
})
export class PoliticasComponent implements OnInit {
  protected readonly colorForName = colorForName;
  private readonly servicio = inject(PoliticaService);
  private readonly directorio = inject(DirectorioService);

  readonly politica = this.servicio.politica;
  readonly guardando = this.servicio.guardando;
  readonly guardadaEn = this.servicio.guardadaEn;

  async ngOnInit(): Promise<void> {
    await this.servicio.cargar();
    this.tomarDeLaPolitica();
    // Las apps de la lista salen del inventario y no de una constante: son las
    // que de verdad corren en la empresa, descubiertas por su propio tráfico.
    void this.directorio.cargarInventario();
  }

  /** Las aplicaciones que Aegis vio corriendo, para poder tratarlas distinto. */
  get aplicaciones(): { nombre: string; modo: string }[] {
    const modos = this.politica().app_actions;
    return this.directorio
      .inventario()
      .filter((f) => f.clase === 'agente')
      .map((f) => ({ nombre: f.nombre, modo: modos[f.nombre] ?? 'bloquear' }));
  }

  async cambiarModoDeApp(nombre: string, modo: string): Promise<void> {
    const app_actions = { ...this.politica().app_actions };
    // 'bloquear' es el valor por defecto: guardarlo explícitamente llenaría la
    // política de filas que no dicen nada. Se quita en vez de escribirse.
    if (modo === 'bloquear') {
      delete app_actions[nombre];
    } else {
      app_actions[nombre] = modo;
    }
    await this.servicio.guardar({ app_actions });
  }

  /** De la política guardada a los controles de la pantalla. */
  private tomarDeLaPolitica(): void {
    const p = this.politica();
    this.urlsBloqueadas = [...p.blocked_domains];
    this.cuentas = [...p.corporate_accounts];
    this.terminos = Object.entries(p.company_terms).map(([termino, etiqueta]) => ({
      termino,
      etiqueta,
    }));
    this.herramientas = this.herramientas.map((h) => ({
      ...h,
      permitida: p.approved_ai.length ? p.approved_ai.includes(dominioDe(h.nombre)) : h.permitida,
    }));
    this.reglasDefault.forEach((r) => {
      const accion = p.rule_actions[reglaId(r.nombre)];
      if (accion) {
        r.activa = accion !== 'off';
        r.accion = accion === 'block' ? 'Bloquear' : accion === 'warn' ? 'Advertir' : r.accion;
      }
    });
    // Las reglas personalizadas no tienen un molde fijo como las de arriba:
    // salen enteras de `custom_rules`, y su estado (activa/bloquea/avisa) sale
    // de `rule_actions` por el mismo id -es la misma perilla que usa una regla
    // de fábrica, el motor no distingue una de otra.
    this.reglasPersonalizadas = p.custom_rules.map((r) => {
      const accion = p.rule_actions[r.id];
      return {
        ...r,
        activa: accion !== 'off',
        accion: accion === 'warn' ? 'Advertir' : 'Bloquear',
      };
    });
  }

  /**
   * Mezcla entradas nuevas sobre el `rule_actions` YA guardado, en vez de
   * reemplazarlo entero. Sin esto, guardar desde "Reglas por defecto" borraba
   * cualquier entrada de una regla personalizada (y viceversa): dos controles
   * de la misma pantalla se pisaban entre sí porque cada uno mandaba su
   * propio recorte del mismo diccionario.
   */
  private conRuleActions(entradas: Record<string, string>): Record<string, string> {
    return { ...this.politica().rule_actions, ...entradas };
  }

  /** Y de vuelta: lo que muestra la pantalla es lo que se guarda. */
  private async persistir(): Promise<void> {
    const reglas: Record<string, string> = {};
    this.reglasDefault.forEach((r) => {
      reglas[reglaId(r.nombre)] = !r.activa
        ? 'off'
        : r.accion === 'Bloquear'
          ? 'block'
          : 'warn';
    });

    const terminos: Record<string, string> = {};
    this.terminos.forEach((t) => {
      if (t.termino.trim()) {
        terminos[t.termino.trim()] = t.etiqueta.trim() || 'interno';
      }
    });

    await this.servicio.guardar({
      approved_ai: this.herramientas.filter((h) => h.permitida).map((h) => dominioDe(h.nombre)),
      blocked_domains: this.urlsBloqueadas,
      rule_actions: this.conRuleActions(reglas),
      company_terms: terminos,
      corporate_accounts: this.cuentas,
    });
  }

  /** El botón de la pantalla. Público porque lo llama la plantilla. */
  async guardar(): Promise<void> {
    await this.persistir();
  }

  // --- Lo que el motor ya sabía hacer y nadie podía configurar --------------
  //
  // Estos cuatro campos existían en la política desde hace rato y no tenían
  // ningún control: se decidían por defecto y para cambiarlos había que editar
  // un JSON a mano. Son las tres detecciones probabilísticas del sistema
  // -modelo, inyección, punto ciego- más el umbral del modelo, y todas
  // comparten el mismo dilema: cortar por una probabilidad es la forma más
  // rápida de que alguien desinstale Aegis, y no cortar es dejar pasar.

  readonly opcionesAccion = [
    { valor: 'block', etiqueta: 'Bloquear el envío' },
    { valor: 'warn', etiqueta: 'Sólo avisar' },
  ];

  async cambiarAvanzado(campo: string, valor: string | boolean): Promise<void> {
    await this.servicio.guardar({ [campo]: valor } as any);
  }

  async cambiarUmbral(valor: string): Promise<void> {
    const numero = Number(valor);
    // Fuera de [0,1] el umbral no significa nada: 0 marca todo y >1 no marca
    // nada, y las dos cosas parecen "el modelo dejó de funcionar".
    if (!Number.isNaN(numero) && numero >= 0 && numero <= 1) {
      await this.servicio.guardar({ model_threshold: numero });
    }
  }

  // --- El diccionario de la empresa ---------------------------------------
  //
  // Es el detector de mayor precisión que hay, porque ningún detector genérico
  // puede tenerlo: nadie sabe que "Proyecto Fénix" es de esta empresa salvo
  // esta empresa. Existía en la política desde hace rato y no tenía ni un
  // campo en toda la UI: sólo se podía escribir por API.
  terminos: { termino: string; etiqueta: string }[] = [];
  nuevoTermino = { termino: '', etiqueta: '' };

  agregarTermino(): void {
    const termino = this.nuevoTermino.termino.trim();
    if (termino && !this.terminos.some((t) => t.termino === termino)) {
      this.terminos = [
        { termino, etiqueta: this.nuevoTermino.etiqueta.trim() || 'interno' },
        ...this.terminos,
      ];
      this.nuevoTermino = { termino: '', etiqueta: '' };
      void this.persistir();
    }
  }

  quitarTermino(termino: string): void {
    this.terminos = this.terminos.filter((t) => t.termino !== termino);
    void this.persistir();
  }

  // "Asignación" (excepciones por persona/área) oculta por ahora: las reglas
  // quedan generales para todo el equipo. El tab y su HTML siguen abajo sin
  // tocar -es un `@if` que ya nadie puede alcanzar por acá-, listos para
  // reactivarse el día que haga falta excepciones puntuales otra vez.
  readonly tabs: TabItem[] = [
    { id: 'herramientas', label: 'Herramientas y URLs' },
    { id: 'dlp', label: 'Reglas de DLP' },
    { id: 'diccionario', label: 'Diccionario de la empresa' },
    { id: 'avanzado', label: 'Detección' },
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
    void this.persistir();
  }

  quitarUrlBloqueada(url: string): void {
    this.urlsBloqueadas = this.urlsBloqueadas.filter((u) => u !== url);
    void this.persistir();
  }

  // --- Cuentas de la empresa ------------------------------------------------
  //
  // Permitir una herramienta no es permitir cualquier cuenta en esa
  // herramienta. Mientras esta lista esté vacía la comprobación está apagada, y
  // eso se dice en pantalla: si no, un administrador que no entiende por qué no
  // pasa nada termina creyendo que la función no sirve.

  cuentas: string[] = [];
  nuevaCuenta = '';

  agregarCuenta(): void {
    const cuenta = this.nuevaCuenta.trim();
    if (!cuenta || this.cuentas.includes(cuenta)) return;
    this.cuentas = [...this.cuentas, cuenta];
    this.nuevaCuenta = '';
    void this.persistir();
  }

  quitarCuenta(cuenta: string): void {
    this.cuentas = this.cuentas.filter((c) => c !== cuenta);
    void this.persistir();
  }

  async cambiarAccionCuentaAjena(accion: string): Promise<void> {
    await this.servicio.guardar({ foreign_account_action: accion });
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

  // --- Reglas propias de la empresa: regex real, no una descripción ---------
  //
  // Esto era decoración: "crear regla" agregaba una tarjeta con una
  // descripción en lenguaje natural que nunca llegaba al motor, porque el
  // motor no interpreta lenguaje natural -interpreta `custom_rules`, que es
  // un patrón regex compilado en `detect/ruleset.py`-. Ahora la tarjeta ES la
  // regla: el patrón que se guarda es el mismo que corre.
  reglasPersonalizadas: (ReglaPersonalizada & { activa: boolean; accion: AccionRegla })[] = [];

  readonly categoriasRegla = [
    { valor: 'secret', etiqueta: 'Secreto' },
    { valor: 'internal_data', etiqueta: 'Dato interno' },
    { valor: 'pii', etiqueta: 'Dato personal' },
  ];
  readonly severidadesRegla = [
    { valor: 'critical', etiqueta: 'Crítica' },
    { valor: 'high', etiqueta: 'Alta' },
    { valor: 'medium', etiqueta: 'Media' },
    { valor: 'low', etiqueta: 'Baja' },
  ];

  nuevaReglaNombre = '';
  nuevaReglaPatron = '';
  nuevaReglaCategoria = 'internal_data';
  nuevaReglaSeveridad = 'high';
  errorNuevaReglaPersonalizada = '';

  agregarReglaPersonalizada(): void {
    const id = this.nuevaReglaNombre.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    const patron = this.nuevaReglaPatron.trim();
    this.errorNuevaReglaPersonalizada = '';

    if (!id || !patron) {
      this.errorNuevaReglaPersonalizada = 'Hace falta un nombre y un patrón.';
      return;
    }
    if (this.reglasPersonalizadas.some((r) => r.id === id)) {
      this.errorNuevaReglaPersonalizada = 'Ya existe una regla con ese nombre.';
      return;
    }
    try {
      // El motor también descarta sola una regex inválida al compilar (ver
      // `detect/ruleset.py`), pero avisar acá evita guardar algo que nunca
      // va a correr y que nadie se va a dar cuenta que no corre.
      new RegExp(patron);
    } catch {
      this.errorNuevaReglaPersonalizada = 'Esa expresión regular no es válida.';
      return;
    }

    this.reglasPersonalizadas = [
      {
        id,
        pattern: patron,
        category: this.nuevaReglaCategoria,
        severity: this.nuevaReglaSeveridad,
        activa: true,
        accion: 'Bloquear',
      },
      ...this.reglasPersonalizadas,
    ];
    this.nuevaReglaNombre = '';
    this.nuevaReglaPatron = '';
    void this.persistirReglasPersonalizadas();
  }

  quitarReglaPersonalizada(id: string): void {
    this.reglasPersonalizadas = this.reglasPersonalizadas.filter((r) => r.id !== id);
    void this.persistirReglasPersonalizadas();
  }

  async alternarReglaPersonalizada(id: string): Promise<void> {
    this.reglasPersonalizadas = this.reglasPersonalizadas.map((r) =>
      r.id === id ? { ...r, activa: !r.activa } : r,
    );
    await this.persistirReglasPersonalizadas();
  }

  async cambiarAccionReglaPersonalizada(id: string, accion: AccionRegla): Promise<void> {
    this.reglasPersonalizadas = this.reglasPersonalizadas.map((r) => (r.id === id ? { ...r, accion } : r));
    await this.persistirReglasPersonalizadas();
  }

  private async persistirReglasPersonalizadas(): Promise<void> {
    const custom_rules: ReglaPersonalizada[] = this.reglasPersonalizadas.map((r) => ({
      id: r.id,
      pattern: r.pattern,
      category: r.category,
      severity: r.severity,
    }));
    const reglas: Record<string, string> = {};
    this.reglasPersonalizadas.forEach((r) => {
      reglas[r.id] = !r.activa ? 'off' : r.accion === 'Bloquear' ? 'block' : 'warn';
    });
    await this.servicio.guardar({ custom_rules, rule_actions: this.conRuleActions(reglas) });
  }

  // --- Que categoria de regla de FORMATO corta, y cual solo avisa -----------
  //
  // Existía en la política desde el principio (`block_categories`,
  // `warn_categories`) y no tenía ningún control: decidía siempre lo mismo
  // por defecto, y para cambiarlo había que editar el JSON a mano.
  readonly categoriasDlp = [
    { valor: 'secret', etiqueta: 'Secretos y credenciales' },
    { valor: 'internal_data', etiqueta: 'Datos internos' },
    { valor: 'pii', etiqueta: 'Datos personales' },
  ];
  readonly opcionesCategoria = [
    { valor: 'block', etiqueta: 'Bloquear el envío' },
    { valor: 'warn', etiqueta: 'Sólo avisar' },
    { valor: 'allow', etiqueta: 'Dejar pasar' },
  ];

  accionDeCategoria(categoria: string): string {
    if (this.politica().block_categories.includes(categoria)) return 'block';
    if (this.politica().warn_categories.includes(categoria)) return 'warn';
    return 'allow';
  }

  async cambiarAccionDeCategoria(categoria: string, accion: string): Promise<void> {
    const block_categories = this.politica().block_categories.filter((c) => c !== categoria);
    const warn_categories = this.politica().warn_categories.filter((c) => c !== categoria);
    if (accion === 'block') block_categories.push(categoria);
    if (accion === 'warn') warn_categories.push(categoria);
    await this.servicio.guardar({ block_categories, warn_categories });
  }

  // --- Terminos prohibidos: un textarea, una categoria compartida -----------
  //
  // No es `company_terms` con otro nombre: produce un hallazgo distinto
  // (`termino_prohibido`) que decide por categoría y no por término. Ver la
  // nota en `politica.service.ts`.
  get terminosProhibidosTexto(): string {
    return this.politica().forbidden_terms.join('\n');
  }

  async guardarTerminosProhibidos(texto: string): Promise<void> {
    const forbidden_terms = texto
      .split('\n')
      .map((t) => t.trim())
      .filter(Boolean);
    await this.servicio.guardar({ forbidden_terms });
  }

  async cambiarCategoriaTerminosProhibidos(categoria: string): Promise<void> {
    await this.servicio.guardar({ forbidden_terms_category: categoria });
  }

  // --- Lo que busca el modelo local, y que autoridad tiene ------------------
  //
  // El modelo (T2) es la tercera detección probabilística del sistema. Por
  // defecto sólo avisa; estas tres perillas le dan más autoridad, categoría
  // por categoría y etiqueta por etiqueta, a la empresa que confíe en él.
  nuevaEtiquetaModelo = '';

  agregarEtiquetaModelo(): void {
    const etiqueta = this.nuevaEtiquetaModelo.trim();
    if (!etiqueta || this.politica().model_labels.includes(etiqueta)) return;
    this.nuevaEtiquetaModelo = '';
    void this.servicio.guardar({ model_labels: [...this.politica().model_labels, etiqueta] });
  }

  quitarEtiquetaModelo(etiqueta: string): void {
    void this.servicio.guardar({
      model_labels: this.politica().model_labels.filter((e) => e !== etiqueta),
      // Una etiqueta que se saca de lo que el modelo busca no puede seguir
      // con autoridad para cortar un envío que ya no va a encontrar.
      model_block_labels: this.politica().model_block_labels.filter((e) => e !== etiqueta),
    });
  }

  tieneAutoridadParaCortar(etiqueta: string): boolean {
    return this.politica().model_block_labels.includes(etiqueta);
  }

  async alternarAutoridadDeEtiqueta(etiqueta: string): Promise<void> {
    const model_block_labels = this.tieneAutoridadParaCortar(etiqueta)
      ? this.politica().model_block_labels.filter((e) => e !== etiqueta)
      : [...this.politica().model_block_labels, etiqueta];
    await this.servicio.guardar({ model_block_labels });
  }

  autorizaModeloEnCategoria(categoria: string): boolean {
    return this.politica().model_block_categories.includes(categoria);
  }

  async alternarAutoridadModeloEnCategoria(categoria: string): Promise<void> {
    const model_block_categories = this.autorizaModeloEnCategoria(categoria)
      ? this.politica().model_block_categories.filter((c) => c !== categoria)
      : [...this.politica().model_block_categories, categoria];
    await this.servicio.guardar({ model_block_categories });
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


/**
 * De un nombre de pantalla al dominio que el agente ve en el tráfico.
 *
 * La política habla de dominios porque es lo único que el proxy tiene delante:
 * "Claude" no aparece en ninguna conexión, "claude.ai" sí.
 */
function dominioDe(nombre: string): string {
  const dominios: Record<string, string> = {
    Claude: 'claude.ai',
    'Claude Code': 'api.anthropic.com',
    ChatGPT: 'chatgpt.com',
    Codex: 'chatgpt.com',
    Gemini: 'gemini.google.com',
    'GitHub Copilot': 'api.githubcopilot.com',
  };
  return dominios[nombre] ?? nombre.toLowerCase().replace(/\s+/g, '');
}

/** Del nombre que ve la empresa al rule_id que usa el motor. */
function reglaId(nombre: string): string {
  const reglas: Record<string, string> = {
    'API keys': 'aws_access_key_id',
    Credenciales: 'credencial_en_espanol',
    'Bases de datos': 'db_connection_string',
  };
  return reglas[nombre] ?? nombre.toLowerCase().replace(/\s+/g, '_');
}
