import { AfterViewInit, Component, ElementRef, HostBinding, Input, OnDestroy, inject } from '@angular/core';
import { SHIELD_MASK } from '../shield-mask';

/**
 * Retícula de puntos que dibuja la silueta del escudo de Aegis y se
 * disuelve en el borde (efecto halftone). Una franja de luz recorre el
 * escudo en loop, como si lo estuviera escaneando. Dos capas con máscara
 * SVG (el escudo con el borde desenfocado), CSS puro.
 *
 * La animación solo corre mientras el escudo está en viewport (se activa
 * al hacer scroll hasta él y se detiene al salir), en vez de correr todo
 * el tiempo en segundo plano.
 */
@Component({
  selector: 'app-halftone-shield',
  standalone: true,
  template: `
    <div class="halftone-dots" [style.--shield-color]="color"></div>
    <div class="halftone-sweep"></div>
  `,
  styles: [`
    :host {
      display: block;
    }
    .halftone-dots,
    .halftone-sweep {
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
      animation: halftone-breathe 6s ease-in-out infinite;
      animation-play-state: paused;
    }
    .halftone-sweep {
      background: linear-gradient(
        to bottom,
        transparent 0%,
        rgba(14, 95, 168, 0.55) 48%,
        rgba(14, 95, 168, 0.55) 52%,
        transparent 100%
      );
      -webkit-mask-image: ${SHIELD_MASK};
      mask-image: ${SHIELD_MASK};
      transform: translateY(-120%);
      animation: halftone-sweep 4.5s ease-in-out infinite;
      animation-play-state: paused;
    }
    :host(.is-visible) .halftone-dots,
    :host(.is-visible) .halftone-sweep {
      animation-play-state: running;
    }
    @keyframes halftone-breathe {
      0%, 100% { opacity: 0.85; }
      50% { opacity: 1; }
    }
    @keyframes halftone-sweep {
      0% { transform: translateY(-120%); }
      45% { transform: translateY(120%); }
      100% { transform: translateY(120%); }
    }
  `],
})
export class HalftoneShieldComponent implements AfterViewInit, OnDestroy {
  private readonly el = inject(ElementRef<HTMLElement>);
  private observer?: IntersectionObserver;

  @Input() color = '#4a5568';

  @HostBinding('class.is-visible') isVisible = false;

  ngAfterViewInit(): void {
    this.observer = new IntersectionObserver(
      ([entry]) => { this.isVisible = entry.isIntersecting; },
      { threshold: 0.3 },
    );
    this.observer.observe(this.el.nativeElement);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }
}
