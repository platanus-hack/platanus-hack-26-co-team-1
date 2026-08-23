import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { RegistroService } from '../../../shared/data/registro.service';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { VerticalStepperComponent } from '../../../shared/ui/vertical-stepper/vertical-stepper.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';

interface EmpresaForm {
  nombre: string;
  descripcion: string;
  sector: string;
  tamano: string;
}

interface AdminForm {
  nombre: string;
  email: string;
  password: string;
  confirmar: string;
}

/** Paso 1 del flujo admin: alta de la cuenta de empresa (form multistep). */
@Component({
  selector: 'app-registro-empresa',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, GradientWavesComponent, VerticalStepperComponent, LogoComponent],
  templateUrl: './registro-empresa.component.html',
})
export class RegistroEmpresaComponent {
  readonly steps = ['Empresa', 'Áreas', 'Administrador'];
  readonly stepTitles = ['Cuéntanos de tu empresa', 'Define tus áreas', 'Crea la cuenta raíz'];
  readonly stepDescriptions = [
    'El sector y el tamaño nos ayudan a sugerir reglas de protección de datos relevantes para ti.',
    'Se reutilizan al dar de alta colaboradores y al asignar políticas.',
    'Esta cuenta gestiona colaboradores, políticas y el panel de actividad.',
  ];
  step = 0;

  empresa: EmpresaForm = { nombre: '', descripcion: '', sector: '', tamano: '' };
  admin: AdminForm = { nombre: '', email: '', password: '', confirmar: '' };

  sectores = ['Finanzas', 'Salud', 'Tecnología', 'Retail', 'Manufactura', 'Legal', 'Educación', 'Otro'];
  tamanos = ['1-10', '11-50', '51-200', '201-500', '500+'];

  areas: string[] = ['Marketing', 'Contabilidad', 'RR.HH.'];
  nuevaArea = '';

  private readonly registro = inject(RegistroService);

  readonly creando = this.registro.creando;
  readonly error = this.registro.error;
  readonly codigoInicial = this.registro.codigoInicial;

  constructor(private router: Router) {}

  agregarArea(): void {
    const valor = this.nuevaArea.trim();
    if (valor && !this.areas.includes(valor)) {
      this.areas.push(valor);
    }
    this.nuevaArea = '';
  }

  quitarArea(area: string): void {
    this.areas = this.areas.filter((a) => a !== area);
  }

  next(): void {
    if (this.step < this.steps.length - 1) this.step++;
  }

  back(): void {
    if (this.step > 0) this.step--;
  }

  /** Antes esto navegaba y no creaba nada: tres pasos que no dejaban rastro. */
  async crearCuenta(): Promise<void> {
    if (this.admin.password !== this.admin.confirmar) {
      this.error.set('Las contraseñas no coinciden.');
      return;
    }
    const empresa = this.empresa.nombre.trim().toLowerCase().replace(/\s+/g, '-');
    const usuario = this.admin.email.trim().toLowerCase();
    if (await this.registro.crear(empresa, usuario, this.admin.password)) {
      // Al paso del código, que es lo único que la persona todavía necesita
      // de esta pantalla: sin él no puede sumar su primer equipo.
      this.step = this.steps.length;
    }
  }

  irAlPanel(): void {
    this.router.navigateByUrl('/admin/colaboradores');
  }
}
