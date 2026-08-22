import { Component, Input } from '@angular/core';

/** Isotipo + wordmark de Aegis: marca lineal, sin badge ni sombra. */
@Component({
  selector: 'app-logo',
  standalone: true,
  template: `
    <div class="flex items-center" [class.gap-2]="small" [class.gap-2.5]="!small" [class.opacity-90]="dim">
      <svg [attr.width]="small ? 22 : 28" [attr.height]="small ? 22 : 28" viewBox="0 0 24 24" fill="none" [class.text-white]="light" [class.text-aegis-text]="!light">
        <path
          d="M12 2.2l7.8 2.9v6c0 5-3.3 8.7-7.8 11-4.5-2.3-7.8-6-7.8-11v-6L12 2.2z"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
        <path d="M8.4 12l2.6 2.6 5-5.3" [attr.stroke]="light ? '#ffcf3d' : '#0e5fa8'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span
        class="font-display font-semibold tracking-[-0.02em]"
        [class.text-lg]="small"
        [class.text-2xl]="!small"
        [class.text-white]="light"
        [class.text-aegis-text]="!light"
      >Aegis</span>
    </div>
  `,
})
export class LogoComponent {
  @Input() dim = false;
  @Input() small = false;
  @Input() light = false;
}
