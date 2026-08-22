import { Component, ElementRef, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';

/**
 * Cuenta de 0 al valor objetivo cuando entra en el viewport. Usa un signal
 * para el valor mostrado: en modo zoneless, requestAnimationFrame por sí
 * solo no dispara detección de cambios, pero escribir un signal sí.
 */
@Component({
  selector: 'app-count-up',
  standalone: true,
  template: `{{ display() }}{{ suffix }}`,
})
export class CountUpComponent implements OnInit, OnDestroy {
  @Input({ required: true }) target = 0;
  @Input() suffix = '';
  @Input() duration = 1400;

  readonly display = signal(0);
  private readonly el = inject(ElementRef<HTMLElement>);
  private observer?: IntersectionObserver;

  ngOnInit(): void {
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
