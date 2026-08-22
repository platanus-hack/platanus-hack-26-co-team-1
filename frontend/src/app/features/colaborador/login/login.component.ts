import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';

/** Inicio de sesión de primer acceso (credenciales entregadas por el administrador). */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, GradientWavesComponent, LogoComponent],
  templateUrl: './login.component.html',
})
export class LoginComponent {
  usuario = '';
  password = '';
  modoRecuperar = false;
  emailRecuperacion = '';
  enviado = false;

  constructor(private router: Router) {}

  ingresar(): void {
    this.router.navigateByUrl('/colaborador/onboarding');
  }

  enviarRecuperacion(): void {
    this.enviado = true;
  }
}
