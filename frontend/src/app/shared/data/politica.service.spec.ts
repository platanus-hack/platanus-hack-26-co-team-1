import { TestBed } from '@angular/core/testing';
import { PoliticaService } from './politica.service';
import { SesionService } from './sesion.service';

/**
 * La política es lo que el agente obedece en cada equipo, así que un error de
 * mapeo acá no se ve en el panel: se ve en que alguien pega una clave y nadie
 * la corta.
 *
 * Dos cosas se prueban por encima del resto. Que la política viaje ENTERA al
 * guardar —mandar un campo suelto depende de que el backend fusione bien, y la
 * pantalla dejaría de ser lo que queda guardado— y que los pedidos lleven la
 * sesión, porque `/v1/policy/` dejó de repartirse sin credencial: lleva
 * `company_terms`, la lista de nombres internos de la empresa.
 */

describe('PoliticaService', () => {
  let servicio: PoliticaService;
  let sesion: SesionService;
  let llamadas: Array<{ url: string; init: RequestInit }>;

  const responder = (cuerpo: unknown, ok = true) => {
    globalThis.fetch = ((url: string, init: RequestInit = {}) => {
      llamadas.push({ url, init });
      return Promise.resolve({
        ok,
        json: () => Promise.resolve(cuerpo),
      } as Response);
    }) as typeof fetch;
  };

  beforeEach(() => {
    llamadas = [];
    localStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    servicio = TestBed.inject(PoliticaService);
    sesion = TestBed.inject(SesionService);
    sesion.adoptar('tok-abc', 'acme', 'jefa', 'admin');
  });

  afterEach(() => localStorage.clear());

  it('leer la política manda la sesión', async () => {
    responder({});
    await servicio.cargar();
    const cabeceras = llamadas[0].init.headers as Record<string, string>;
    expect(cabeceras['Authorization']).toBe('Bearer tok-abc');
  });

  it('una empresa sin política guardada igual llena la pantalla', async () => {
    // El backend devuelve {} y la pantalla tiene que tener todos los campos:
    // un select sin valor no se ve como "sin configurar", se ve como vacío.
    responder({});
    await servicio.cargar();
    expect(servicio.politica().company_terms_action).toBe('block');
    expect(servicio.politica().model_threshold).toBe(0.7);
    expect(servicio.cargada()).toBe(false);
  });

  it('lo que viene del backend le gana al molde', async () => {
    responder({ company_terms: { Quimera: 'codename' }, model_threshold: 0.9 });
    await servicio.cargar();
    expect(servicio.politica().company_terms).toEqual({ Quimera: 'codename' });
    expect(servicio.politica().model_threshold).toBe(0.9);
    expect(servicio.cargada()).toBe(true);
  });

  it('guardar manda la política entera y no sólo el campo que cambió', async () => {
    responder({ approved_ai: ['claude.ai'], model_threshold: 0.9 });
    await servicio.cargar();

    responder({});
    await servicio.guardar({ ocr_enabled: true });

    const enviado = JSON.parse(llamadas[1].init.body as string);
    expect(enviado.ocr_enabled).toBe(true);
    expect(enviado.approved_ai).toEqual(['claude.ai']);
    expect(enviado.model_threshold).toBe(0.9);
    expect(enviado.tenant_id).toBe('acme');
  });

  it('guardar manda la sesión y usa PUT', async () => {
    responder({});
    await servicio.guardar({ ocr_enabled: true });
    expect(llamadas[0].init.method).toBe('PUT');
    const cabeceras = llamadas[0].init.headers as Record<string, string>;
    expect(cabeceras['Authorization']).toBe('Bearer tok-abc');
  });

  it('si el backend rechaza, la pantalla no miente', async () => {
    responder({}, false);
    const ok = await servicio.guardar({ ocr_enabled: true });
    expect(ok).toBe(false);
    expect(servicio.politica().ocr_enabled).toBe(false);
    expect(servicio.guardadaEn()).toBeNull();
  });

  it('sin servidor tampoco miente', async () => {
    globalThis.fetch = (() => Promise.reject(new Error('sin red'))) as typeof fetch;
    const ok = await servicio.guardar({ ocr_enabled: true });
    expect(ok).toBe(false);
    expect(servicio.guardando()).toBe(false);
  });
});
