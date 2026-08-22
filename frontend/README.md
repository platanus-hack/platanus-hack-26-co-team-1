# Aegis UI

Frontend en Angular de Aegis: landing pública, flujos de colaborador (login,
onboarding, actividad) y panel de administrador (registro de empresa,
colaboradores, políticas, agent inventory, dashboards). Standalone
components, Tailwind CSS y efectos WebGL propios (`ogl`) para los fondos
animados.

## Desarrollo

```bash
npm install
npm start        # ng serve (http://localhost:4200)
```

## Build

```bash
npm run build     # dist/aegis-ui
```

## Tests

```bash
npm test          # Vitest
```

## Estructura

```
src/app/
  features/
    colaborador/   Landing, login, onboarding, actividad
    admin/         Shell, registro de empresa, colaboradores, políticas,
                    agent inventory, paneles
  shared/
    ui/            Componentes de presentación reutilizables (badge, tabs,
                    logo, avatar-stack, ...)
    effects/       Fondos y gráficos animados (gradient-waves, radar,
                    halftone-shield)
```
