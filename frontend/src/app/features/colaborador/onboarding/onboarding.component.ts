import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { VerticalStepperComponent } from '../../../shared/ui/vertical-stepper/vertical-stepper.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';

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

  nuevaPassword = '';
  confirmarPassword = '';

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

  next(): void {
    if (this.step < this.steps.length - 1) this.step++;
  }

  back(): void {
    if (this.step > 0) this.step--;
  }

  finalizar(): void {
    this.router.navigateByUrl('/colaborador/actividad');
  }
}
