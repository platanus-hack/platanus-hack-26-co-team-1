import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { SesionService } from './sesion.service';

/**
 * Manda al login a quien no entro.
 *
 * Esto es comodidad, no seguridad: quien quiera puede saltarselo con la consola
 * del navegador. Lo que de verdad protege los datos es que `/api/metrics`
 * devuelve 401 sin token y saca el tenant de adentro del token firmado. El
 * guard existe para que la pantalla no se vea vacia y sin explicacion, no para
 * defender nada.
 */
export const sesionGuard: CanActivateFn = () => {
  const sesion = inject(SesionService);
  const router = inject(Router);
  return sesion.autenticado() ? true : router.createUrlTree(['/colaborador/login']);
};
