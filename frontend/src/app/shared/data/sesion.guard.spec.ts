import { TestBed } from '@angular/core/testing';
import { Router, UrlTree } from '@angular/router';
import { provideRouter } from '@angular/router';
import { sesionGuard } from './sesion.guard';
import { SesionService } from './sesion.service';

/**
 * El guard es comodidad, no seguridad — quien quiera se lo salta con la
 * consola. Lo que protege los datos es que el API contesta 401 sin token.
 *
 * Se prueba igual porque su trabajo también se puede romper: si dejara pasar,
 * quien no entró vería un panel vacío sin ninguna explicación; si bloqueara de
 * más, nadie entraría. Los dos fallos son invisibles hasta que alguien los sufre.
 */

describe('sesionGuard', () => {
  let sesion: SesionService;

  const correr = () =>
    TestBed.runInInjectionContext(() => sesionGuard(null as never, null as never));

  beforeEach(() => {
    localStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    sesion = TestBed.inject(SesionService);
  });

  afterEach(() => localStorage.clear());

  it('sin sesión manda al login', () => {
    const salida = correr();
    expect(salida).toBeInstanceOf(UrlTree);
    expect(TestBed.inject(Router).serializeUrl(salida as UrlTree)).toBe(
      '/colaborador/login',
    );
  });

  it('con sesión deja pasar', () => {
    sesion.adoptar('tok', 'acme', 'jefa', 'admin');
    expect(correr()).toBe(true);
  });

  it('después de salir vuelve a mandar al login', () => {
    sesion.adoptar('tok', 'acme', 'jefa', 'admin');
    sesion.salir();
    expect(correr()).toBeInstanceOf(UrlTree);
  });
});
