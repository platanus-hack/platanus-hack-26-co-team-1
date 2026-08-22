import { Component, Input } from '@angular/core';
import { colorForName, initialsOf } from '../../utils/color-hash';

const TAMANOS = {
  sm: { box: 'h-7 w-7', text: 'text-[10px]' },
  md: { box: 'h-9 w-9', text: 'text-xs' },
  lg: { box: 'h-12 w-12', text: 'text-sm' },
};

/** Quiénes: iniciales superpuestas con color estable por nombre, y un "+N" con el resto en el tooltip. */
@Component({
  selector: 'app-avatar-stack',
  standalone: true,
  template: `
    <div class="flex items-center -space-x-2" [attr.aria-label]="names.join(', ')">
      @for (n of visibles; track n) {
        <span
          class="flex shrink-0 items-center justify-center rounded-full border-2 border-aegis-surface font-semibold text-white"
          [class]="tamano.box + ' ' + tamano.text"
          [style.background]="colorForName(n)"
          [title]="n"
        >{{ initialsOf(n) }}</span>
      }
      @if (resto > 0) {
        <span
          class="flex shrink-0 items-center justify-center rounded-full border-2 border-aegis-surface bg-aegis-surface3 font-semibold text-aegis-dim"
          [class]="tamano.box + ' ' + tamano.text"
          [title]="ocultos.join(', ')"
        >+{{ resto }}</span>
      }
    </div>
  `,
})
export class AvatarStackComponent {
  @Input({ required: true }) names: string[] = [];
  @Input() max = 3;
  @Input() size: 'sm' | 'md' | 'lg' = 'sm';

  protected readonly colorForName = colorForName;
  protected readonly initialsOf = initialsOf;

  get tamano() {
    return TAMANOS[this.size];
  }

  get visibles(): string[] {
    return this.names.slice(0, this.max);
  }

  get resto(): number {
    return Math.max(this.names.length - this.max, 0);
  }

  get ocultos(): string[] {
    return this.names.slice(this.max);
  }
}
