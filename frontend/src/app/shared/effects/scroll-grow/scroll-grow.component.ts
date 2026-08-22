import { ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';

/**
 * Fondo que crece de ancho atado a la posición de scroll: arranca angosto
 * y llega al ancho completo de la pantalla a medida que el host entra
 * desde abajo hasta llegar arriba del todo. Baja igual si se vuelve a
 * subir. Se usa como un `<div>` más (position: absolute) dentro de un
 * contenedor `position: relative`; el contenido proyectado (el fondo en
 * sí, vía `<ng-content>`) es lo único que crece, cualquier otro contenido
 * de la página no se entera.
 *
 * El tamaño REAL en el DOM queda fijo en el máximo desde el arranque
 * (`anchoFinal`, todo el ancho de la pantalla): lo único que cambia con el
 * scroll es un `transform: scaleX()`, que es puro trabajo de GPU/
 * compositor. Es a propósito, no una simplificación cualquiera: si en vez
 * de esto se anima el `width` real, cada cambio dispara el
 * `ResizeObserver` de lo que esté proyectado adentro — y `gradient-waves`
 * es un canvas WebGL, así que cada frame de scroll terminaba reescalando
 * (`renderer.setSize`) el framebuffer entero, que es carísimo y es lo que
 * hacía sentir el scroll pesado. Escalar con `transform` no toca layout,
 * no dispara ese observer, y el canvas se dimensiona una sola vez.
 *
 * Además evita el layout thrashing clásico de este tipo de efectos: en
 * vez de leer `getBoundingClientRect()` (fuerza un reflow) en cada scroll,
 * la posición del host en el documento se mide una sola vez (al iniciar y
 * en cada resize) y en scroll solo se resta `window.scrollY` — una
 * lectura barata, sin reflow.
 */
@Component({
  selector: 'app-scroll-grow',
  standalone: true,
  host: {
    class: 'absolute inset-y-0 left-1/2 overflow-hidden',
    '[style.width.px]': 'anchoFinal()',
    '[style.transform]': "'translateX(-50%) scaleX(' + escalaX() + ')'",
  },
  template: `<ng-content></ng-content>`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScrollGrowComponent implements OnInit, OnDestroy {
  @Input() anchoInicial = 1152;

  private readonly host = inject(ElementRef<HTMLElement>);

  readonly anchoFinal = signal(0);
  readonly escalaX = signal(1);

  private topDocumento = 0;
  private anchoCompleto = 0;
  private raf = 0;
  private onScroll = () => this.pedirActualizacion();
  private onResize = () => {
    this.medir();
    this.actualizar();
  };

  ngOnInit(): void {
    this.medir();
    this.actualizar();
    window.addEventListener('scroll', this.onScroll, { passive: true });
    window.addEventListener('resize', this.onResize, { passive: true });
  }

  ngOnDestroy(): void {
    window.removeEventListener('scroll', this.onScroll);
    window.removeEventListener('resize', this.onResize);
    if (this.raf) cancelAnimationFrame(this.raf);
  }

  /** Posición absoluta en el documento (no en el viewport) y ancho de pantalla: cambian con resize, no con scroll. */
  private medir(): void {
    const rect = this.host.nativeElement.getBoundingClientRect();
    this.topDocumento = rect.top + window.scrollY;
    // clientWidth del <html>, no innerWidth: así no cuenta el ancho de la
    // barra de scroll y el fondo no termina más ancho que la página.
    this.anchoCompleto = document.documentElement.clientWidth;
    this.anchoFinal.set(this.anchoCompleto);
  }

  private pedirActualizacion(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.actualizar();
    });
  }

  private actualizar(): void {
    // Sin leer el DOM: la posición actual en viewport es la absoluta menos
    // lo scrolleado, y window.scrollY no fuerza un reflow como
    // getBoundingClientRect().
    const top = this.topDocumento - window.scrollY;
    const vh = window.innerHeight || 1;
    // 0 cuando el borde superior está a la altura del borde inferior de la
    // pantalla (recién entrando), 1 cuando llega al borde superior.
    const progreso = Math.min(Math.max((vh - top) / vh, 0), 1);

    const escalaInicial = this.anchoCompleto > 0 ? this.anchoInicial / this.anchoCompleto : 1;
    this.escalaX.set(escalaInicial + (1 - escalaInicial) * progreso);
  }
}
