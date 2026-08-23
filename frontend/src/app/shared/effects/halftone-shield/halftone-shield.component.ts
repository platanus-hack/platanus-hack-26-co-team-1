import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, inject, signal } from '@angular/core';
import { SHIELD_MASK } from '../shield-mask';

/**
 * Retícula de puntos que dibuja la silueta del escudo de Aegis y se
 * disuelve en el borde (efecto halftone). Un pulso de luz late desde el
 * centro hacia afuera, como un sonar, más los propios puntos respirando
 * (opacidad + escala). Dos capas con máscara SVG (el escudo con el borde
 * desenfocado), CSS puro.
 *
 * La animación solo corre mientras el escudo está en viewport (se activa
 * al hacer scroll hasta él y se detiene al salir), en vez de correr todo
 * el tiempo en segundo plano.
 */
@Component({
  selector: 'app-halftone-shield',
  standalone: true,
  host: { '[class.is-visible]': 'isVisible()' },
  template: `
    <div class="halftone-dots" [style.--shield-color]="color"></div>
    <div class="halftone-pulse-layer"></div>
  `,
  styles: [`
    :host {
      display: block;
    }
    .halftone-dots,
    .halftone-pulse-layer {
      position: absolute;
      inset: 0;
      -webkit-mask-size: contain;
      mask-size: contain;
      -webkit-mask-position: center;
      mask-position: center;
      -webkit-mask-repeat: no-repeat;
      mask-repeat: no-repeat;
    }
    .halftone-dots {
      color: var(--shield-color, #4a5568);
      background-image: radial-gradient(currentColor 32%, transparent 34%);
      background-size: 9px 9px;
      -webkit-mask-image: ${SHIELD_MASK};
      mask-image: ${SHIELD_MASK};
      transform-origin: center;
      animation: halftone-breathe 6s ease-in-out infinite;
      animation-play-state: paused;
    }
    .halftone-pulse-layer {
      background: radial-gradient(circle at 50% 46%, rgba(14, 95, 168, 0.65) 0%, rgba(14, 95, 168, 0.3) 32%, transparent 66%);
      -webkit-mask-image: ${SHIELD_MASK};
      mask-image: ${SHIELD_MASK};
      transform-origin: 50% 46%;
      transform: scale(0.5);
      opacity: 0;
      animation: halftone-pulse 4s ease-out infinite;
      animation-play-state: paused;
    }
    :host(.is-visible) .halftone-dots,
    :host(.is-visible) .halftone-pulse-layer {
      animation-play-state: running;
    }
    @keyframes halftone-breathe {
      0%, 100% { opacity: 0.85; transform: scale(1); }
      50% { opacity: 1; transform: scale(1.015); }
    }
    @keyframes halftone-pulse {
      0% { transform: scale(0.5); opacity: 0; }
      18% { opacity: 0.9; }
      70% { transform: scale(1.2); opacity: 0; }
      100% { transform: scale(1.2); opacity: 0; }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HalftoneShieldComponent implements AfterViewInit, OnDestroy {
  private readonly el = inject(ElementRef<HTMLElement>);
  private observer?: IntersectionObserver;

  @Input() color = '#4a5568';

  // Signal, no un campo plano: la app corre zoneless, así que solo escribir
  // un signal (y no un booleano suelto) hace que Angular vuelva a evaluar
  // el host binding cuando el IntersectionObserver dispara.
  readonly isVisible = signal(false);

  ngAfterViewInit(): void {
    this.observer = new IntersectionObserver(
      ([entry]) => { this.isVisible.set(entry.isIntersecting); },
      { threshold: 0.3 },
    );
    this.observer.observe(this.el.nativeElement);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }
}
