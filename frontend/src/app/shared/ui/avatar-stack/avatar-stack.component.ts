import { Component, Input } from '@angular/core';

const PALETA = ['#0e5fa8', '#a8710a', '#177a52', '#c93a4c', '#0a4879'];

/** Quiénes: iniciales superpuestas con color estable por nombre, y un "+N" con el resto en el tooltip. */
@Component({
  selector: 'app-avatar-stack',
  standalone: true,
  template: `
    <div class="flex items-center -space-x-2" [attr.aria-label]="names.join(', ')">
      @for (n of visibles; track n) {
        <span
          class="flex h-7 w-7 items-center justify-center rounded-full border-2 border-aegis-surface text-[10px] font-semibold text-white"
          [style.background]="colorFor(n)"
          [title]="n"
        >{{ initials(n) }}</span>
      }
      @if (resto > 0) {
        <span
          class="flex h-7 w-7 items-center justify-center rounded-full border-2 border-aegis-surface bg-aegis-surface3 text-[10px] font-semibold text-aegis-dim"
          [title]="ocultos.join(', ')"
        >+{{ resto }}</span>
      }
    </div>
  `,
})
export class AvatarStackComponent {
  @Input({ required: true }) names: string[] = [];
  @Input() max = 3;

  get visibles(): string[] {
    return this.names.slice(0, this.max);
  }

  get resto(): number {
    return Math.max(this.names.length - this.max, 0);
  }

  get ocultos(): string[] {
    return this.names.slice(this.max);
  }

  initials(name: string): string {
    return name
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map((parte) => parte[0]?.toUpperCase() ?? '')
      .join('');
  }

  colorFor(name: string): string {
    let hash = 0;
    for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return PALETA[hash % PALETA.length];
  }
}
