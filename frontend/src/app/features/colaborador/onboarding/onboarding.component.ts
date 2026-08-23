import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { VerticalStepperComponent } from '../../../shared/ui/vertical-stepper/vertical-stepper.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { SesionService } from '../../../shared/data/sesion.service';

type Perfil = 'tecnico' | 'no_tecnico';
type Experiencia = 'ninguna' | 'basica' | 'avanzada';

/** Onboarding posterior al primer login: nueva contraseña + cuestionario de contexto. */
@Component({
  selector: 'app-onboarding',
  standalone: true,
  imports: [CommonModule, FormsModule, GradientWavesComponent, VerticalStepperComponent, LogoComponent],
  templateUrl: './onboarding.component.html',
})
export class OnboardingComponent {
  readonly steps = ['Nueva contraseña', 'Cuestionario de contexto'];
  readonly stepTitles = ['Asegura tu cuenta', 'Cuéntanos cómo trabajas'];
  readonly stepDescriptions = [
    'La contraseña que te dio tu administrador es solo para este primer ingreso.',
    'Esto ajusta el tono de las explicaciones y qué reglas son más relevantes para ti.',
  ];
  step = 0;

  private readonly sesion = inject(SesionService);

  // Precargada si venís recién del login (ver login.component.ts); si no
  // -recarga de página, o quien sea que abrió este link solo-, queda vacía y
  // hay que volver a escribirla: es la misma temporal que ya sirvió para
  // entrar, así que pedirla de nuevo no es un paso de más, es la confirmación
  // de que quien la está cambiando es quien la tiene.
  contrasenaActual = this.sesion.contrasenaRecien();
  nuevaPassword = '';
  confirmarPassword = '';
  readonly errorPassword = signal<string | null>(null);
  readonly cambiando = signal(false);

  perfil: Perfil | null = null;
  experiencia: Experiencia | null = null;
  readonly experienciaOpciones: { id: Experiencia; label: string }[] = [
    { id: 'ninguna', label: 'Ninguna' },
    { id: 'basica', label: 'Básica' },
    { id: 'avanzada', label: 'Avanzada' },
  ];

  readonly usosDisponibles = ['Redacción', 'Análisis de datos', 'Código', 'Investigación', 'Traducción'];
  usos: string[] = [];

  readonly tiposDatoDisponibles = [
    'Datos de clientes',
    'Información financiera',
    'Código fuente',
    'Estrategia de negocio',
    'Ninguno de los anteriores',
  ];
  tiposDato: string[] = [];

  constructor(private router: Router) {}

  toggle(lista: string[], valor: string): void {
    const i = lista.indexOf(valor);
    if (i >= 0) lista.splice(i, 1);
    else lista.push(valor);
  }

  async next(): Promise<void> {
    if (this.step === 0) {
      await this.confirmarNuevaPassword();
    } else if (this.step < this.steps.length - 1) {
      this.step++;
    }
  }

  /**
   * El paso 0 no es "seguir" hasta que la contraseña de verdad cambió en el
   * backend: avanzar sin eso dejaría a la persona pensando que ya no usa la
   * temporal, cuando en realidad seguiría siendo la única que sirve.
   */
  private async confirmarNuevaPassword(): Promise<void> {
    this.errorPassword.set(null);

    if (!this.contrasenaActual.trim()) {
      this.errorPassword.set('Escribí la contraseña temporal que te dio tu administrador.');
      return;
    }
    if (this.nuevaPassword.length < 8) {
      this.errorPassword.set('La contraseña nueva necesita al menos 8 caracteres.');
      return;
    }
    if (this.nuevaPassword !== this.confirmarPassword) {
      this.errorPassword.set('Las dos contraseñas no coinciden.');
      return;
    }

    this.cambiando.set(true);
    const fallo = await this.sesion.cambiarPassword(this.contrasenaActual, this.nuevaPassword);
    this.cambiando.set(false);

    if (fallo) {
      this.errorPassword.set(fallo);
    } else {
      this.step++;
    }
  }

  back(): void {
    if (this.step > 0) this.step--;
  }

  finalizar(): void {
    this.router.navigateByUrl('/colaborador/actividad');
  }
}
