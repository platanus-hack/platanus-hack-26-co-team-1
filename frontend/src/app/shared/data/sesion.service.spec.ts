import { TestBed } from '@angular/core/testing';
import { SesionService } from './sesion.service';

/**
 * La pieza del frontend que más duele si se rompe en silencio.
 *
 * `cabeceras()` es lo único que hace que el API sepa quién pregunta. Si
 * devolviera un objeto vacío, cada pantalla del panel se vería vacía y sin
 * ningún error visible — el servidor contestaría 401 y la UI mostraría cero
 * eventos, que es exactamente lo que muestra una empresa que todavía no tuvo
 * ninguno. Un bug que se ve igual que el caso feliz no lo encuentra nadie
 * mirando la pantalla.
 */

const CLAVE = 'aegis.sesion';

describe('SesionService', () => {
  let servicio: SesionService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    servicio = TestBed.inject(SesionService);
  });

  afterEach(() => localStorage.clear());

  it('sin sesión no manda ninguna cabecera', () => {
    expect(servicio.cabeceras()).toEqual({});
    expect(servicio.autenticado()).toBe(false);
  });

  it('con sesión manda el Bearer', () => {
    servicio.adoptar('tok-123', 'acme', 'jefa', 'admin');
    expect(servicio.cabeceras()).toEqual({ Authorization: 'Bearer tok-123' });
    expect(servicio.autenticado()).toBe(true);
  });

  it('adoptar no pierde el rol', () => {
    // Antes esto era `{ token, tenant, usuario } as Sesion`: el cast tapaba que
    // quien se registraba quedaba sin rol hasta volver a entrar por el login.
    servicio.adoptar('tok', 'acme', 'jefa', 'admin');
    expect(servicio.sesion()?.rol).toBe('admin');
  });

  it('salir deja de mandar la cabecera y borra lo guardado', () => {
    servicio.adoptar('tok', 'acme', 'jefa', 'admin');
    servicio.salir();
    expect(servicio.cabeceras()).toEqual({});
    expect(localStorage.getItem(CLAVE)).toBeNull();
  });

  it('la sesión sobrevive a recargar la página', () => {
    servicio.adoptar('tok', 'acme', 'jefa', 'admin');

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const recargado = TestBed.inject(SesionService);

    expect(recargado.cabeceras()).toEqual({ Authorization: 'Bearer tok' });
    expect(recargado.tenant()).toBe('acme');
  });

  it('un localStorage con basura no deja la app rota', () => {
    // Pasa de verdad: una versión vieja del objeto, o alguien tocando la
    // consola. Arrancar sin sesión es correcto; tirar una excepción al
    // construir el servicio deja el panel en blanco.
    localStorage.setItem(CLAVE, '{no es json');

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({});
    const nuevo = TestBed.inject(SesionService);

    expect(nuevo.autenticado()).toBe(false);
  });

  it('el tenant que muestra es informativo y no pide datos', () => {
    // El servidor saca el tenant de adentro del token firmado. Este valor es
    // para escribirlo en pantalla: si mintiera, el API seguiría devolviendo los
    // datos de la empresa de verdad.
    servicio.adoptar('tok', 'acme', 'jefa', 'admin');
    expect(servicio.tenant()).toBe('acme');
    expect(servicio.cabeceras()['Authorization']).not.toContain('acme');
  });
});
