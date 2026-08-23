import { Routes } from '@angular/router';
import { sesionGuard } from './shared/data/sesion.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'colaborador/landing' },

  {
    path: 'admin/registro',
    loadComponent: () =>
      import('./features/admin/registro-empresa/registro-empresa.component').then((m) => m.RegistroEmpresaComponent),
  },

  {
    path: 'admin',
    // Sin sesion, al login. Es comodidad y no seguridad: lo que protege los
    // datos es que /api/metrics devuelve 401 sin token y saca el tenant de
    // adentro del token firmado, no este guard.
    canActivate: [sesionGuard],
    loadComponent: () =>
      import('./features/admin/shell/admin-shell.component').then((m) => m.AdminShellComponent),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'colaboradores' },
      {
        path: 'colaboradores',
        loadComponent: () =>
          import('./features/admin/colaboradores/colaboradores.component').then((m) => m.ColaboradoresComponent),
      },
      {
        path: 'politicas',
        loadComponent: () =>
          import('./features/admin/politicas/politicas.component').then((m) => m.PoliticasComponent),
      },
      {
        path: 'panel',
        loadComponent: () =>
          import('./features/admin/panel-general/panel-general.component').then((m) => m.PanelGeneralComponent),
      },
      {
        path: 'lectura',
        loadComponent: () =>
          import('./features/admin/lectura-semana/lectura-semana.component').then(
            (m) => m.LecturaSemanaComponent,
          ),
      },
      {
        path: 'panel/:id',
        loadComponent: () =>
          import('./features/admin/panel-colaborador/panel-colaborador.component').then((m) => m.PanelColaboradorComponent),
      },
      {
        path: 'inventario',
        loadComponent: () =>
          import('./features/admin/inventario/inventario.component').then((m) => m.InventarioComponent),
      },
    ],
  },

  {
    path: 'colaborador',
    children: [
      {
        path: 'landing',
        loadComponent: () =>
          import('./features/colaborador/landing/landing.component').then((m) => m.LandingComponent),
      },
      {
        path: 'login',
        loadComponent: () =>
          import('./features/colaborador/login/login.component').then((m) => m.LoginComponent),
      },
      {
        path: 'onboarding',
        loadComponent: () =>
          import('./features/colaborador/onboarding/onboarding.component').then((m) => m.OnboardingComponent),
      },
      {
        path: 'actividad',
        loadComponent: () =>
          import('./features/colaborador/actividad/actividad.component').then((m) => m.ActividadComponent),
      },
    ],
  },

  { path: '**', redirectTo: 'colaborador/landing' },
];
