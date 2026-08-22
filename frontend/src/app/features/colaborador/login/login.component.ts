import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GradientWavesComponent } from '../../../shared/effects/gradient-waves/gradient-waves.component';
import { LogoComponent } from '../../../shared/ui/logo/logo.component';
import { SesionService } from '../../../shared/data/sesion.service';

/**
 * Inicio de sesión.
 *
 * Antes navegaba a onboarding sin mirar lo que se escribía: el formulario era
 * una maqueta y el panel de administración estaba abierto para cualquiera.
 * Ahora consulta `/v1/login`, y si la respuesta es buena guarda el token con el
 * que el API decide qué datos devolver.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, GradientWavesComponent, LogoComponent],
  templateUrl: './login.component.html',
})
export class LoginComponent {
  private readonly sesion = inject(SesionService);
  private readonly router = inject(Router);

  usuario = '';
  password = '';
  modoRecuperar = false;
  emailRecuperacion = '';
  enviado = false;

  readonly error = signal<string | null>(null);
  readonly entrando = signal(false);

  async ingresar(): Promise<void> {
    this.error.set(null);
    this.entrando.set(true);
    const fallo = await this.sesion.entrar(this.usuario, this.password);
    this.entrando.set(false);

    if (fallo) {
      this.error.set(fallo);
    } else {
      // Al panel: quien entra con una cuenta de administración viene a ver los
      // datos de su empresa, no a instalar el agente otra vez.
      this.router.navigateByUrl('/admin/panel');
    }
  }

  enviarRecuperacion(): void {
    this.enviado = true;
  }
}
