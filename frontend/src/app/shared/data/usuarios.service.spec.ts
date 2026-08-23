import { TestBed } from '@angular/core/testing';
import { SesionService } from './sesion.service';
import { UsuariosService } from './usuarios.service';

/**
 * Lo que se prueba acá es el contrato con el servidor, no la pantalla.
 *
 * Dos cosas por encima del resto: que el tenant NUNCA viaje —el servidor lo
 * saca del token firmado, y mandarlo desde acá sería darle a cualquiera la
 * forma de administrar el equipo de otra empresa— y que el error del servidor
 * llegue tal cual a la pantalla, porque está escrito para que lo lea una
 * persona y reemplazarlo por un "algo salió mal" borra la única pista útil.
 */

describe('UsuariosService', () => {
  let servicio: UsuariosService;
  let llamadas: Array<{ url: string; init: RequestInit }>;

  const responder = (cuerpo: unknown, ok = true) => {
    globalThis.fetch = ((url: string, init: RequestInit = {}) => {
      llamadas.push({ url, init });
      return Promise.resolve({ ok, json: () => Promise.resolve(cuerpo) } as Response);
    }) as typeof fetch;
  };

  beforeEach(() => {
    llamadas = [];
    localStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    servicio = TestBed.inject(UsuariosService);
    TestBed.inject(SesionService).adoptar('tok-abc', 'acme', 'jefa', 'admin');
  });

  afterEach(() => localStorage.clear());

  it('la lista llega con la sesión', async () => {
    responder({ usuarios: [{ usuario: 'jefa', rol: 'admin' }], yo: 'jefa' });
    await servicio.cargar();

    const cabeceras = llamadas[0].init.headers as Record<string, string>;
    expect(cabeceras['Authorization']).toBe('Bearer tok-abc');
    expect(servicio.usuarios()).toEqual([{ usuario: 'jefa', rol: 'admin' }]);
    expect(servicio.yo()).toBe('jefa');
  });

  it('el tenant no viaja en ningún lado', async () => {
    // El servidor lo saca del token. Si viajara, cambiarlo acá alcanzaría para
    // administrar el equipo de otra empresa.
    responder({ usuarios: [] });
    await servicio.sumar('nuevo', 'clave-larga-1', 'lector');

    const enviado = llamadas[0];
    expect(enviado.url).not.toContain('acme');
    expect(JSON.parse(enviado.init.body as string).tenant).toBeUndefined();
  });

  it('sumar manda usuario, contraseña y rol', async () => {
    responder({ usuarios: [] });
    await servicio.sumar('nuevo', 'clave-larga-1', 'lector');

    expect(JSON.parse(llamadas[0].init.body as string)).toEqual({
      usuario: 'nuevo',
      password: 'clave-larga-1',
      rol: 'lector',
    });
  });

  it('cambiar el rol no manda contraseña', async () => {
    responder({ usuarios: [] });
    await servicio.cambiarRol('mirona', 'admin');

    const enviado = JSON.parse(llamadas[0].init.body as string);
    expect(enviado).toEqual({ usuario: 'mirona', rol: 'admin' });
    expect(enviado.password).toBeUndefined();
  });

  it('dar de baja va marcado y no se confunde con un alta', async () => {
    responder({ usuarios: [] });
    await servicio.darDeBaja('mirona');
    expect(JSON.parse(llamadas[0].init.body as string)).toEqual({
      usuario: 'mirona',
      baja: true,
    });
  });

  it('una escritura buena refresca la lista', async () => {
    // Si no, la pantalla muestra el estado viejo y quien acaba de sumar a
    // alguien cree que no funcionó.
    responder({ usuarios: [{ usuario: 'nuevo', rol: 'lector' }] });
    await servicio.sumar('nuevo', 'clave-larga-1', 'lector');

    expect(llamadas.length).toBe(2);
    expect(llamadas[1].init.method).toBeUndefined();
    expect(servicio.usuarios()).toEqual([{ usuario: 'nuevo', rol: 'lector' }]);
  });

  it('el motivo del rechazo se muestra tal cual lo dijo el servidor', async () => {
    responder({ error: 'no se puede cambiar ese rol' }, false);
    const ok = await servicio.cambiarRol('jefa', 'lector');

    expect(ok).toBe(false);
    expect(servicio.error()).toBe('no se puede cambiar ese rol');
  });

  it('sin servidor no se queda guardando para siempre', async () => {
    globalThis.fetch = (() => Promise.reject(new Error('sin red'))) as typeof fetch;
    const ok = await servicio.sumar('nuevo', 'clave-larga-1', 'lector');

    expect(ok).toBe(false);
    expect(servicio.guardando()).toBe(false);
    expect(servicio.error()).toBeTruthy();
  });

  it('un error viejo no sobrevive al siguiente intento', async () => {
    responder({ error: 'no se puede' }, false);
    await servicio.cambiarRol('jefa', 'lector');
    expect(servicio.error()).toBeTruthy();

    responder({ usuarios: [] });
    await servicio.cambiarRol('mirona', 'admin');
    expect(servicio.error()).toBeNull();
  });
});
