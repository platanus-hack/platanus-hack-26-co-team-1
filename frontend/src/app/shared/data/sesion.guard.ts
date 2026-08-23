import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { SesionService } from './sesion.service';

/**
 * Manda al login a quien no entro.
 *
 * Esto es comodidad, no seguridad: quien quiera puede saltarselo con la consola
 * del navegador. Lo que de verdad protege los datos es que `/api/metrics` (y
 * `/v1/mi-actividad`, y todo lo demas) devuelve 401 sin token y saca el
 * usuario/tenant de adentro del token firmado. El guard existe para que la
 * pantalla no se vea vacia y sin explicacion, no para defender nada.
 */
export const sesionGuard: CanActivateFn = () => {
  const sesion = inject(SesionService);
  const router = inject(Router);
  return sesion.autenticado() ? true : router.createUrlTree(['/colaborador/login']);
};

/**
 * Lo mismo que arriba, pero para /admin: ademas de haber entrado, tiene que
 * ser una cuenta de administracion. Una cuenta de colaborador que adivine la
 * URL no ve el panel de la empresa -y de nuevo, esto es comodidad: el 401 real
 * lo pone el servidor mirando el rol adentro del token firmado, nunca esto-.
 */
export const adminGuard: CanActivateFn = () => {
  const sesion = inject(SesionService);
  const router = inject(Router);
  if (!sesion.autenticado()) return router.createUrlTree(['/colaborador/login']);
  return sesion.rol() === 'admin' ? true : router.createUrlTree(['/colaborador/actividad']);
};
