import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, ViewChild } from '@angular/core';
import { Mesh, Program, Renderer, Triangle } from 'ogl';

function hexToVec3(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255];
}

const VERTEX = `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0, 1);
}
`;

const FRAGMENT = `
precision highp float;

uniform float uTime;
uniform vec3 uResolution;
uniform float uSpeed;
uniform float uScale;
uniform float uRingCount;
uniform float uSpokeCount;
uniform float uRingThickness;
uniform float uSpokeThickness;
uniform float uSweepSpeed;
uniform float uSweepWidth;
uniform float uSweepLobes;
uniform vec3 uColor;
uniform vec3 uBgColor;
uniform float uFalloff;
uniform float uBrightness;
uniform vec2 uMouse;
uniform float uMouseInfluence;
uniform bool uEnableMouse;

#define TAU 6.28318530718
#define PI 3.14159265359

void main() {
  vec2 st = gl_FragCoord.xy / uResolution.xy;
  st = st * 2.0 - 1.0;
  st.x *= uResolution.x / uResolution.y;

  if (uEnableMouse) {
    vec2 mShift = (uMouse * 2.0 - 1.0);
    mShift.x *= uResolution.x / uResolution.y;
    st -= mShift * uMouseInfluence;
  }

  st *= uScale;

  float dist = length(st);
  float theta = atan(st.y, st.x);
  float t = uTime * uSpeed;

  float ringPhase = dist * uRingCount - t;
  float ringDist = abs(fract(ringPhase) - 0.5);
  float ringGlow = 1.0 - smoothstep(0.0, uRingThickness, ringDist);

  float spokeAngle = abs(fract(theta * uSpokeCount / TAU + 0.5) - 0.5) * TAU / uSpokeCount;
  float arcDist = spokeAngle * dist;
  float spokeGlow = (1.0 - smoothstep(0.0, uSpokeThickness, arcDist)) * smoothstep(0.0, 0.1, dist);

  float sweepPhase = t * uSweepSpeed;
  float sweepBeam = pow(max(0.5 * sin(uSweepLobes * theta + sweepPhase) + 0.5, 0.0), uSweepWidth);

  float fade = smoothstep(1.05, 0.85, dist) * pow(max(1.0 - dist, 0.0), uFalloff);

  float intensity = max((ringGlow + spokeGlow + sweepBeam) * fade * uBrightness, 0.0);
  vec3 col = uColor * intensity + uBgColor;

  float alpha = clamp(length(col), 0.0, 1.0);
  gl_FragColor = vec4(col, alpha);
}
`;

/**
 * Puerto a Angular/OGL del componente "Radar" de reactbits.dev
 * (https://reactbits.dev/backgrounds/radar): anillos concéntricos y un
 * barrido giratorio en WebGL. `ogl` no depende de React, así que el hook
 * original se traslada casi literal a los hooks de ciclo de vida de
 * Angular. Color por defecto en el azul de marca.
 */
@Component({
  selector: 'app-radar',
  standalone: true,
  template: `<div #container class="radar-container"></div>`,
  styles: [`
    :host {
      position: absolute;
      inset: 0;
      display: block;
      overflow: hidden;
      pointer-events: none;
    }
    .radar-container {
      width: 100%;
      height: 100%;
    }
    .radar-container canvas {
      display: block;
      width: 100%;
      height: 100%;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RadarComponent implements AfterViewInit, OnDestroy {
  @ViewChild('container', { static: true }) containerRef!: ElementRef<HTMLDivElement>;

  @Input() speed = 1.0;
  @Input() scale = 0.5;
  @Input() ringCount = 10;
  @Input() spokeCount = 10;
  @Input() ringThickness = 0.05;
  @Input() spokeThickness = 0.01;
  @Input() sweepSpeed = 1.0;
  @Input() sweepWidth = 2.0;
  @Input() sweepLobes = 1;
  @Input() color = '#1f7bc4';
  @Input() backgroundColor = '#000000';
  @Input() falloff = 2.0;
  @Input() brightness = 1.0;
  @Input() enableMouseInteraction = true;
  @Input() mouseInfluence = 0.1;

  private renderer?: Renderer;
  private raf = 0;
  private canvas?: HTMLCanvasElement;
  private resizeHandler?: () => void;
  private onMouseMove?: (e: MouseEvent) => void;
  private onMouseLeave?: () => void;

  ngAfterViewInit(): void {
    const container = this.containerRef.nativeElement;
    const renderer = new Renderer({ alpha: true, premultipliedAlpha: false });
    this.renderer = renderer;
    const gl = renderer.gl;
    gl.clearColor(0, 0, 0, 0);

    let currentMouse: [number, number] = [0.5, 0.5];
    let targetMouse: [number, number] = [0.5, 0.5];

    const program = new Program(gl, {
      vertex: VERTEX,
      fragment: FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uResolution: { value: [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height] },
        uSpeed: { value: this.speed },
        uScale: { value: this.scale },
        uRingCount: { value: this.ringCount },
        uSpokeCount: { value: this.spokeCount },
        uRingThickness: { value: this.ringThickness },
        uSpokeThickness: { value: this.spokeThickness },
        uSweepSpeed: { value: this.sweepSpeed },
        uSweepWidth: { value: this.sweepWidth },
        uSweepLobes: { value: this.sweepLobes },
        uColor: { value: hexToVec3(this.color) },
        uBgColor: { value: hexToVec3(this.backgroundColor) },
        uFalloff: { value: this.falloff },
        uBrightness: { value: this.brightness },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uMouseInfluence: { value: this.mouseInfluence },
        uEnableMouse: { value: this.enableMouseInteraction },
      },
    });

    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });
    const canvas = gl.canvas;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    container.appendChild(canvas);
    this.canvas = canvas;

    const resize = () => {
      renderer.setSize(container.offsetWidth, container.offsetHeight);
      program.uniforms['uResolution'].value = [gl.canvas.width, gl.canvas.height, gl.canvas.width / gl.canvas.height];
    };
    this.resizeHandler = resize;
    window.addEventListener('resize', resize);
    resize();

    if (this.enableMouseInteraction) {
      this.onMouseMove = (e: MouseEvent) => {
        const rect = canvas.getBoundingClientRect();
        targetMouse = [(e.clientX - rect.left) / rect.width, 1.0 - (e.clientY - rect.top) / rect.height];
      };
      this.onMouseLeave = () => {
        targetMouse = [0.5, 0.5];
      };
      canvas.addEventListener('mousemove', this.onMouseMove);
      canvas.addEventListener('mouseleave', this.onMouseLeave);
    }

    const update = (time: number) => {
      this.raf = requestAnimationFrame(update);
      program.uniforms['uTime'].value = time * 0.001;

      if (this.enableMouseInteraction) {
        currentMouse[0] += 0.05 * (targetMouse[0] - currentMouse[0]);
        currentMouse[1] += 0.05 * (targetMouse[1] - currentMouse[1]);
        (program.uniforms['uMouse'].value as Float32Array)[0] = currentMouse[0];
        (program.uniforms['uMouse'].value as Float32Array)[1] = currentMouse[1];
      } else {
        (program.uniforms['uMouse'].value as Float32Array)[0] = 0.5;
        (program.uniforms['uMouse'].value as Float32Array)[1] = 0.5;
      }

      renderer.render({ scene: mesh });
    };
    this.raf = requestAnimationFrame(update);
  }

  ngOnDestroy(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.resizeHandler) window.removeEventListener('resize', this.resizeHandler);
    if (this.canvas) {
      if (this.onMouseMove) this.canvas.removeEventListener('mousemove', this.onMouseMove);
      if (this.onMouseLeave) this.canvas.removeEventListener('mouseleave', this.onMouseLeave);
      this.canvas.remove();
    }
    this.renderer?.gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
