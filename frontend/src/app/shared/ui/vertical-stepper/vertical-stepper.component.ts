import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

/** Stepper vertical para el panel lateral de formularios multistep. */
@Component({
  selector: 'app-vertical-stepper',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './vertical-stepper.component.html',
})
export class VerticalStepperComponent {
  @Input({ required: true }) steps: string[] = [];
  @Input({ required: true }) activeIndex = 0;

  state(i: number): 'done' | 'active' | 'pending' {
    if (i < this.activeIndex) return 'done';
    if (i === this.activeIndex) return 'active';
    return 'pending';
  }
}
