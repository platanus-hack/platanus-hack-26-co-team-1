import { Component, Input } from '@angular/core';

/** Tile de KPI para dashboards (panel general del administrador). */
@Component({
  selector: 'app-stat-tile',
  standalone: true,
  template: `
    <div class="aegis-card flex flex-col gap-3 p-5">
      <span class="aegis-label">{{ label }}</span>
      <div class="flex items-end justify-between gap-2">
        <span class="font-display text-3xl font-semibold text-aegis-text">{{ value }}</span>
        @if (trend) {
          <span
            class="mb-1 font-display text-xs font-medium"
            [class.text-aegis-red]="trendUp"
            [class.text-aegis-green]="!trendUp"
          >{{ trend }}</span>
        }
      </div>
    </div>
  `,
})
export class StatTileComponent {
  @Input({ required: true }) label = '';
  @Input({ required: true }) value = '';
  @Input() trend = '';
  @Input() trendUp = false;
}
