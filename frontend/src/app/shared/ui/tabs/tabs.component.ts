import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface TabItem {
  id: string;
  label: string;
}

/** Control segmentado para sub-secciones que comparten pantalla (tabs internos). */
@Component({
  selector: 'app-tabs',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="inline-flex gap-1 rounded-lg border border-aegis-border bg-aegis-surface2 p-1">
      @for (tab of tabs; track tab.id) {
        <button
          type="button"
          class="rounded-md px-3.5 py-1.5 font-display text-xs uppercase tracking-wide transition-colors"
          [class]="tab.id === active ? 'bg-aegis-accent text-white' : 'text-aegis-dim'"
          (click)="select(tab.id)"
        >
          {{ tab.label }}
        </button>
      }
    </div>
  `,
})
export class TabsComponent {
  @Input({ required: true }) tabs: TabItem[] = [];
  @Input({ required: true }) active = '';
  @Output() activeChange = new EventEmitter<string>();

  select(id: string): void {
    this.activeChange.emit(id);
  }
}
