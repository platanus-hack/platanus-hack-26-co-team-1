import { Component, Input } from '@angular/core';

export type BadgeTone = 'accent' | 'amber' | 'red' | 'green' | 'neutral';

const TONE_CLASSES: Record<BadgeTone, string> = {
  accent: 'bg-aegis-accent/10 text-aegis-accent border-aegis-accent/30',
  amber: 'bg-aegis-amber/10 text-aegis-amber border-aegis-amber/30',
  red: 'bg-aegis-red/10 text-aegis-red border-aegis-red/30',
  green: 'bg-aegis-green/10 text-aegis-green border-aegis-green/30',
  neutral: 'bg-aegis-surface3 text-aegis-dim border-aegis-border',
};

/** Pastilla de estado (bloqueado / advertido / activo / pendiente, etc.). */
@Component({
  selector: 'app-badge',
  standalone: true,
  template: `
    <span class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-display text-[11px] uppercase tracking-wide" [class]="toneClass">
      <ng-content></ng-content>
    </span>
  `,
})
export class BadgeComponent {
  @Input() tone: BadgeTone = 'neutral';

  get toneClass(): string {
    return TONE_CLASSES[this.tone];
  }
}
