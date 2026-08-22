import { ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';

/**
 * Cuenta de 0 al valor objetivo cuando entra en el viewport. Usa un signal
 * para el valor mostrado: en modo zoneless, requestAnimationFrame por sí
 * solo no dispara detección de cambios, pero escribir un signal sí.
 *
 * Mientras cuenta pasa por menos dígitos que el valor final (0, 1... 15), y
 * sin más eso corre el texto de al lado. Se reserva el ancho final (dígitos
 * del target + sufijo) desde el arranque para que nada se mueva alrededor.
 */
@Component({
  selector: 'app-count-up',
  standalone: true,
  host: {
    style: 'display: inline-block; font-variant-numeric: tabular-nums;',
    '[style.min-width.ch]': 'anchoCh',
  },
  template: `{{ display() }}{{ suffix }}`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CountUpComponent implements OnInit, OnDestroy {
  @Input({ required: true }) target = 0;
  @Input() suffix = '';
  @Input() duration = 1400;

  readonly display = signal(0);
  anchoCh = 0;

  private readonly el = inject(ElementRef<HTMLElement>);
  private observer?: IntersectionObserver;

  ngOnInit(): void {
    this.anchoCh = String(this.target).length + this.suffix.length;

    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          this.animate();
          this.observer?.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    this.observer.observe(this.el.nativeElement);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  private animate(): void {
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - start) / this.duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      this.display.set(Math.round(this.target * eased));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}
