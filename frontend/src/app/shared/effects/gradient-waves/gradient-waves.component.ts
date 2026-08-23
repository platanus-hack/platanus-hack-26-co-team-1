import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, ViewChild } from '@angular/core';
import { Mesh, Program, Renderer, Triangle } from 'ogl';

function hexToRgb(hex: string): [number, number, number] {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return [1, 1, 1];
  return [parseInt(result[1], 16) / 255, parseInt(result[2], 16) / 255, parseInt(result[3], 16) / 255];
}

function detailToSteps(detail: string): number {
  if (detail === 'low') return 40.0;
  if (detail === 'high') return 110.0;
  return 70.0;
}

const VERTEX = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 iResolution;
uniform float iTime;
uniform float uSpeed;
uniform float uAmplitude;
uniform float uWaveScale;
uniform float uWaveRatio;
uniform float uSwell;
uniform float uTurbulence;
uniform float uTilt;
uniform float uZoom;
uniform float uHeight;
uniform float uFogDepth;
uniform float uSteps;
uniform float uBrightness;
uniform float uOpacity;
uniform float uGrain;
uniform float uGrainIntensity;
uniform vec2 uMouse;
uniform float uParallax;
uniform bool uEnableMouse;
uniform vec3 uHorizonColor;
uniform vec3 uWaveColor;
uniform vec3 uCrestColor;
out vec4 fragColor;

const float MAX_DIST = 20000.0;

float hash21(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

float plasma(vec3 r, vec2 freq, vec4 tc) {
  float mx = r.x + tc.x;
  mx += uSwell * sin((r.y + mx) / 20.0 + tc.y);
  float my = r.y - tc.z;
  my += uTurbulence * cos(r.x / 23.0 + tc.w);
  return r.z - (sin(mx * freq.x) * uAmplitude + sin(my * freq.y) * uAmplitude + uHeight);
}

float raymarch(vec3 pos, vec3 dir, vec2 freq, vec4 tc) {
  float dist = 0.0;
  for (int i = 0; i < 128; i++) {
    if (float(i) >= uSteps) break;
    float dscene = plasma(pos + dist * dir, freq, tc);
    if (abs(dscene) < 0.1) break;
    dist += 0.9 * dscene;
    if (!(abs(dist) < MAX_DIST)) return MAX_DIST;
  }
  return dist;
}

void main() {
  float T = iTime * uSpeed;
  vec2 freq = vec2(uWaveScale / 7.0, (uWaveScale * uWaveRatio) / 3.0);
  vec4 tc = vec4(T / 0.130, T / 0.810, T / 0.200, T / 0.710);
  float c, s;
  float vfov = (3.14159 / 2.3) / max(uZoom, 0.05);
  vec3 cam = vec3(0.0, 0.0, 30.0);
  vec2 uv = (gl_FragCoord.xy / iResolution.xy) - 0.5;
  uv.x *= iResolution.x / iResolution.y;
  uv.y *= -1.0;

  vec3 dir = vec3(0.0, 0.0, -1.0);
  float ulen = length(uv);
  float xrot = vfov * ulen;
  c = cos(xrot); s = sin(xrot);
  dir = mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c) * dir;
  vec2 nuv = ulen > 1e-5 ? uv / ulen : vec2(1.0, 0.0);
  c = nuv.x; s = nuv.y;
  dir = mat3(c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0) * dir;
  c = cos(uTilt); s = sin(uTilt);
  dir = mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c) * dir;

  if (uEnableMouse) {
    float yaw = (uMouse.x - 0.5) * uParallax * 0.4;
    float pitch = (uMouse.y - 0.5) * uParallax * 0.4;
    c = cos(yaw); s = sin(yaw);
    dir = mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c) * dir;
    c = cos(pitch); s = sin(pitch);
    dir = mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c) * dir;
  }

  float dist = raymarch(cam, dir, freq, tc);
  vec3 pos = cam + dist * dir;

  float t = clamp(uFogDepth / max(dist, 0.001), 0.0, 1.0);
  vec3 body = mix(uWaveColor, uCrestColor, clamp(pos.z * 0.08 + 0.5, 0.0, 1.0));
  vec3 col = mix(uHorizonColor, body, t);
  col *= uBrightness;
  col = clamp(col, 0.0, 1.0);

  float alpha = clamp(t, 0.0, 1.0) * uOpacity;
  if (uGrain > 0.5) {
    float g = hash21(gl_FragCoord.xy + mod(iTime, 64.0) * 11.0);
    alpha += (g - 0.5) * uGrainIntensity;
  }
  alpha = clamp(alpha, 0.0, 1.0);
  fragColor = vec4(col * alpha, alpha);
}
`;

/**
 * Puerto a Angular/OGL del componente "Gradient Waves" de reactbits.dev
 * (https://reactbits.dev/backgrounds/gradient-waves): campo de olas por
 * raymarching en WebGL2 puro. `ogl` no depende de React, así que la lógica
 * del hook original se traslada casi literal a los hooks de ciclo de vida
 * de Angular. Tonos azules por defecto para encajar con la marca.
 */
@Component({
  selector: 'app-gradient-waves',
  standalone: true,
  template: `<div #container class="gradient-waves-container"></div>`,
  styles: [`
    :host {
      position: absolute;
      inset: 0;
      display: block;
      overflow: hidden;
      pointer-events: none;
    }
    .gradient-waves-container {
      position: relative;
      width: 100%;
      height: 100%;
      overflow: hidden;
    }
    .gradient-waves-container canvas {
      display: block;
      width: 100%;
      height: 100%;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GradientWavesComponent implements AfterViewInit, OnDestroy {
  @ViewChild('container', { static: true }) containerRef!: ElementRef<HTMLDivElement>;

  @Input() horizonColor = '#031b33';
  @Input() waveColor = '#1f7cc9';
  @Input() crestColor = '#8ad9ff';
  @Input() speed = 0.5;
  @Input() amplitude = 2.8;
  @Input() waveScale = 0.6;
  @Input() waveRatio = 0.9;
  @Input() swell = 38;
  @Input() turbulence = 22;
  @Input() tilt = 1.11;
  @Input() zoom = 1.0;
  @Input() height = 5.5;
  @Input() fogDepth = 15;
  @Input() detail: 'low' | 'medium' | 'high' = 'medium';
  @Input() brightness = 1.15;
  @Input() opacity = 1.0;
  @Input() mouseInteraction = true;
  @Input() parallaxStrength = 0.4;
  @Input() grain = true;
  @Input() grainIntensity = 0.04;

  private renderer?: Renderer;
  private raf = 0;
  private resizeObserver?: ResizeObserver;
  private intersectionObserver?: IntersectionObserver;
  private canvas?: HTMLCanvasElement;
  private onPointerMove?: (e: PointerEvent) => void;
  private onPointerLeave?: () => void;
  private onVisibility?: () => void;

  ngAfterViewInit(): void {
    const container = this.containerRef.nativeElement;

    const renderer = new Renderer({
      webgl: 2,
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      dpr: Math.min(window.devicePixelRatio || 1, 2),
    });
    this.renderer = renderer;

    const gl = renderer.gl;
    gl.clearColor(0, 0, 0, 0);
    const canvas = gl.canvas;
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    container.appendChild(canvas);
    this.canvas = canvas;

    const program = new Program(gl, {
      vertex: VERTEX,
      fragment: FRAGMENT,
      uniforms: {
        iTime: { value: 0 },
        iResolution: { value: new Float32Array([1, 1]) },
        uSpeed: { value: this.speed },
        uAmplitude: { value: this.amplitude },
        uWaveScale: { value: this.waveScale },
        uWaveRatio: { value: this.waveRatio },
        uSwell: { value: this.swell },
        uTurbulence: { value: this.turbulence },
        uTilt: { value: this.tilt },
        uZoom: { value: this.zoom },
        uHeight: { value: this.height },
        uFogDepth: { value: this.fogDepth },
        uSteps: { value: detailToSteps(this.detail) },
        uBrightness: { value: this.brightness },
        uOpacity: { value: this.opacity },
        uGrain: { value: this.grain ? 1.0 : 0.0 },
        uGrainIntensity: { value: this.grainIntensity },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uParallax: { value: this.parallaxStrength },
        uEnableMouse: { value: this.mouseInteraction },
        uHorizonColor: { value: new Float32Array(hexToRgb(this.horizonColor)) },
        uWaveColor: { value: new Float32Array(hexToRgb(this.waveColor)) },
        uCrestColor: { value: new Float32Array(hexToRgb(this.crestColor)) },
      },
    });

    const mesh = new Mesh(gl, { geometry: new Triangle(gl), program });

    const setSize = () => {
      const rect = container.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      renderer.setSize(w, h);
      const res = program.uniforms['iResolution'].value as Float32Array;
      res[0] = gl.drawingBufferWidth;
      res[1] = gl.drawingBufferHeight;
      renderer.render({ scene: mesh });
    };

    this.resizeObserver = new ResizeObserver(setSize);
    this.resizeObserver.observe(container);
    setSize();

    const currentMouse = [0.5, 0.5];
    const targetMouse = [0.5, 0.5];

    this.onPointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      targetMouse[0] = (e.clientX - rect.left) / rect.width;
      targetMouse[1] = 1.0 - (e.clientY - rect.top) / rect.height;
    };
    this.onPointerLeave = () => {
      targetMouse[0] = 0.5;
      targetMouse[1] = 0.5;
    };
    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerleave', this.onPointerLeave);

    let isVisible = true;
    let isPageVisible = !document.hidden;
    const t0 = performance.now();

    const loop = (t: number) => {
      program.uniforms['iTime'].value = (t - t0) * 0.001;
      const tx = this.mouseInteraction ? targetMouse[0] : 0.5;
      const ty = this.mouseInteraction ? targetMouse[1] : 0.5;
      currentMouse[0] += 0.05 * (tx - currentMouse[0]);
      currentMouse[1] += 0.05 * (ty - currentMouse[1]);
      (program.uniforms['uMouse'].value as Float32Array)[0] = currentMouse[0];
      (program.uniforms['uMouse'].value as Float32Array)[1] = currentMouse[1];
      renderer.render({ scene: mesh });
      this.raf = requestAnimationFrame(loop);
    };

    const tryStart = () => {
      if (isVisible && isPageVisible && this.raf === 0) this.raf = requestAnimationFrame(loop);
    };
    const tryStop = () => {
      if (this.raf !== 0) {
        cancelAnimationFrame(this.raf);
        this.raf = 0;
      }
    };

    this.intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        isVisible = entry.isIntersecting;
        isVisible ? tryStart() : tryStop();
      },
      { threshold: 0 },
    );
    this.intersectionObserver.observe(container);

    this.onVisibility = () => {
      isPageVisible = !document.hidden;
      isPageVisible ? tryStart() : tryStop();
    };
    document.addEventListener('visibilitychange', this.onVisibility);

    tryStart();
  }

  ngOnDestroy(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.resizeObserver?.disconnect();
    this.intersectionObserver?.disconnect();
    if (this.onVisibility) document.removeEventListener('visibilitychange', this.onVisibility);
    if (this.canvas) {
      if (this.onPointerMove) this.canvas.removeEventListener('pointermove', this.onPointerMove);
      if (this.onPointerLeave) this.canvas.removeEventListener('pointerleave', this.onPointerLeave);
      this.canvas.remove();
    }
    this.renderer?.gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}
