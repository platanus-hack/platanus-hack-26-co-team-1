import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { HalftoneShieldComponent } from '../../../shared/effects/halftone-shield/halftone-shield.component';
import { ParticlesFieldComponent } from '../../../shared/effects/particles-field/particles-field.component';
import { RadarComponent } from '../../../shared/effects/radar/radar.component';
import { ScrollGrowComponent } from '../../../shared/effects/scroll-grow/scroll-grow.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { CountUpComponent } from '../../../shared/ui/count-up/count-up.component';

interface Stat {
  target: number;
  finding: string;
  source: string;
}

/** Landing pública, sin login. Único punto de contacto antes de instalar la app. */
@Component({
  selector: 'app-landing',
  standalone: true,
  imports: [
    RouterLink,
    GradientWavesComponent,
    HalftoneShieldComponent,
    ParticlesFieldComponent,
    RadarComponent,
    ScrollGrowComponent,
    LogoComponent,
    CountUpComponent,
  ],
  templateUrl: './landing.component.html',
  // Sin esto, en una app zoneless cualquier signal que cambia en CUALQUIER
  // parte del árbol agenda un tick que revisa igual TODOS los bindings de
  // esta plantilla entera (partículas, radar, cada stat con su count-up,
  // etc). El scroll-grow escribe un signal en cada frame de scroll, así
  // que sin OnPush eso eran decenas de recorridos completos por segundo,
  // solo mientras se scrollea esa sección: por eso ahí y no en el resto.
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingComponent {
  readonly pasos = [
    { titulo: 'Descarga el instalador', detalle: 'Disponible para macOS, Windows y Linux.' },
    { titulo: 'Inicia sesión', detalle: 'Usa las credenciales que te entregó tu administrador.' },
    { titulo: 'Sigue usando tu IA de siempre', detalle: 'Aegis corre en segundo plano, sin cambiar tu flujo de trabajo.' },
  ];

  readonly headlineStat = {
    from: 15,
    to: 45,
    finding: 'Proporción de empleados que usa IA de forma regular en dispositivos corporativos (un salto interanual de 15% a 45%). El shadow AI ya es la tercera acción interna no maliciosa más común en datos de DLP, 4x en un año.',
    source: 'Verizon, 2026 Data Breach Investigations Report',
  };

  readonly stats: Stat[] = [
    {
      target: 67,
      finding: 'De los empleados que usan IA desde dispositivos corporativos lo hace con cuentas personales, no corporativas.',
      source: 'Verizon, 2026 DBIR',
    },
    {
      target: 89,
      finding: 'De las organizaciones en Latinoamérica sufrió al menos un incidente de seguridad relacionado con APIs este año.',
      source: 'Akamai, 2026',
    },
    {
      target: 42,
      finding: 'De los profesionales de seguridad afirma que las APIs de sus IAs o agentes fueron blanco de ciberataques.',
      source: 'Akamai, 2026',
    },
    {
      target: 27,
      finding: 'De las organizaciones con inventario completo de APIs sabe cuáles exponen datos sensibles (caía del 40% en 2022).',
      source: 'Akamai, 2026',
    },
  ];
}
