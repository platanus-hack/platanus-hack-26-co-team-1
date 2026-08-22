import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

/**
 * Shell del administrador: sidebar de navegación + topbar.
 * Envuelve tanto las pantallas de configuración inicial como el panel.
 * Mismo tratamiento azul de marca que el sidebar de onboarding/registro
 * (gradiente + gradient-waves), para que se sienta el mismo producto en
 * vez de una consola gris genérica.
 */
@Component({
  selector: 'app-admin-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, LogoComponent, GradientWavesComponent],
  templateUrl: './admin-shell.component.html',
})
export class AdminShellComponent {
  readonly nav: NavItem[] = [
    { path: '/admin/panel', label: 'Panel general', icon: 'chart' },
    { path: '/admin/colaboradores', label: 'Colaboradores', icon: 'users' },
    { path: '/admin/politicas', label: 'Políticas', icon: 'shield' },
    { path: '/admin/inventario', label: 'Agent Inventory', icon: 'radar' },
  ];

  /** Sidebar como drawer fuera de pantalla en mobile/tablet; fija (position: fixed) desde lg. */
  sidebarOpen = false;
}
