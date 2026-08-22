import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';

interface Particula {
  left: number;
  top: number;
  size: number;
  blur: number;
  dx: number;
  dy: number;
  delay: number;
  duration: number;
  opacidadMax: number;
}

/**
 * Sistema de partículas del color del escudo flotando de fondo: suben,
 * se mecen de lado a lado y se desvanecen en los bordes del ciclo (así el
 * loop no se nota). Delays negativos para que arranquen ya distribuidas en
 * pleno vuelo, no todas sincronizadas desde cero. Igual que el resto de los
 * efectos, la animación solo corre mientras está en viewport.
 */
@Component({
  selector: 'app-particles-field',
  standalone: true,
  host: { '[class.is-visible]': 'isVisible()' },
  template: `
    @for (p of particulas; track $index) {
      <span
        class="particula"
        [style.left.%]="p.left"
        [style.top.%]="p.top"
        [style.width.px]="p.size"
        [style.height.px]="p.size"
        [style.background]="color"
        [style.filter]="p.blur ? 'blur(' + p.blur + 'px)' : null"
        [style.--dx.px]="p.dx"
        [style.--dy.px]="p.dy"
        [style.--op-max]="p.opacidadMax"
        [style.animation-delay.s]="p.delay"
        [style.animation-duration.s]="p.duration"
      ></span>
    }
  `,
  styles: [`
    :host {
      display: block;
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
    }
    .particula {
      position: absolute;
      border-radius: 9999px;
      opacity: 0;
      animation-name: particula-flotar;
      animation-timing-function: ease-in-out;
      animation-iteration-count: infinite;
      animation-play-state: paused;
    }
    :host(.is-visible) .particula {
      animation-play-state: running;
    }
    @keyframes particula-flotar {
      0% { transform: translate(0, 0) scale(0.85); opacity: 0; }
      12% { opacity: var(--op-max); }
      50% { transform: translate(var(--dx), calc(var(--dy) * 0.5)) scale(1.15); }
      88% { opacity: var(--op-max); }
      100% { transform: translate(0, var(--dy)) scale(0.85); opacity: 0; }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ParticlesFieldComponent implements OnInit, AfterViewInit, OnDestroy {
  @Input() color = '#0e5fa8';
  @Input() count = 42;

  // Signal, no un campo plano: la app corre zoneless, así que solo escribir
  // un signal (y no un booleano suelto) hace que Angular vuelva a evaluar
  // el host binding cuando el IntersectionObserver dispara.
  readonly isVisible = signal(false);

  private readonly el = inject(ElementRef<HTMLElement>);
  private observer?: IntersectionObserver;

  particulas: Particula[] = [];

  ngOnInit(): void {
    // En ngOnInit (no como inicializador de campo) para que ya tome el
    // @Input() count real, no el default, si alguien lo personaliza.
    this.particulas = Array.from({ length: this.count }, () => {
      const grande = Math.random() < 0.2;
      const size = grande ? 7 + Math.random() * 7 : 3 + Math.random() * 6;
      const duration = 6 + Math.random() * 9;
      return {
        left: Math.random() * 100,
        top: Math.random() * 100,
        size,
        blur: grande ? size / 5 : 0,
        dx: (Math.random() - 0.5) * 70,
        dy: -(220 + Math.random() * 340),
        duration,
        // Negativo: cada una arranca en un punto distinto de su ciclo,
        // como si el sistema ya llevara rato corriendo.
        delay: -Math.random() * duration,
        opacidadMax: grande ? 0.15 + Math.random() * 0.15 : 0.35 + Math.random() * 0.45,
      };
    });
  }

  ngAfterViewInit(): void {
    this.observer = new IntersectionObserver(
      ([entry]) => { this.isVisible.set(entry.isIntersecting); },
      { threshold: 0 },
    );
    this.observer.observe(this.el.nativeElement);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }
}
