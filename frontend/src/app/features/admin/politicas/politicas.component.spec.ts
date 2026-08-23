import { TestBed } from '@angular/core/testing';
import { PoliticasComponent } from './politicas.component';
import { PoliticaService } from '../../../shared/data/politica.service';
import { SesionService } from '../../../shared/data/sesion.service';

/**
 * La whitelist de herramientas: lo que la pantalla dice tiene que ser lo que la
 * política guarda.
 *
 * El bug que motiva este archivo: ChatGPT y Codex eran dos filas y un solo
 * destino (`chatgpt.com`). Como el guardado hace
 * `filter(permitida).map(dominio)`, con ChatGPT permitido y Codex bloqueado el
 * dominio se guardaba igual — el toggle de Codex no hacía absolutamente nada, y
 * nadie se enteraba. Es la peor clase de bug de UI: no falla, miente.
 */

describe('PoliticasComponent · whitelist de herramientas', () => {
  let componente: PoliticasComponent;
  let guardado: Record<string, unknown> | null;

  beforeEach(() => {
    guardado = null;
    localStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    TestBed.inject(SesionService).adoptar('tok', 'acme', 'jefa', 'admin');

    const servicio = TestBed.inject(PoliticaService);
    servicio.guardar = async (cambio: Record<string, unknown>) => {
      guardado = cambio;
      return true;
    };
    componente = TestBed.createComponent(PoliticasComponent).componentInstance;
  });

  afterEach(() => localStorage.clear());

  const dominiosGuardados = () => (guardado?.['approved_ai'] as string[]) ?? [];

  it('cada fila es un destino distinto', async () => {
    // La invariante que hace que los toggles signifiquen algo. Dos filas con el
    // mismo dominio son dos interruptores para una sola decisión: uno pisa al
    // otro y el que pierde no avisa.
    const dominios = componente.herramientas.map((h) => h.dominio);
    expect(new Set(dominios).size).toBe(dominios.length);
  });

  it('apagar una herramienta la saca de la política', async () => {
    const chatgpt = componente.herramientas.find((h) => h.dominio === 'chatgpt.com')!;
    chatgpt.permitida = false;
    await componente['persistir']();

    expect(dominiosGuardados()).not.toContain('chatgpt.com');
  });

  it('prenderla la devuelve', async () => {
    const gemini = componente.herramientas.find((h) => h.dominio === 'gemini.google.com')!;
    gemini.permitida = true;
    await componente['persistir']();

    expect(dominiosGuardados()).toContain('gemini.google.com');
  });

  it('se guarda el dominio y no el nombre que se ve en pantalla', async () => {
    // El nombre puede decir "ChatGPT · Codex"; lo que entiende el motor es el host.
    await componente['persistir']();
    for (const dominio of dominiosGuardados()) {
      expect(dominio).toMatch(/\./);
      expect(dominio).not.toContain(' ');
    }
  });

  it('lo que llega del backend prende y apaga los toggles correctos', () => {
    // La otra mitad del contrato: si al leer se emparejara por nombre en vez de
    // por dominio, la pantalla mostraría permisos que no son los guardados.
    const servicio = TestBed.inject(PoliticaService);
    servicio.politica.set({ ...servicio.politica(), approved_ai: ['claude.ai'] });
    componente['tomarDeLaPolitica']();

    const permitidas = componente.herramientas.filter((h) => h.permitida).map((h) => h.dominio);
    expect(permitidas).toEqual(['claude.ai']);
  });
});
