export type EstadoColaborador = 'activo' | 'pendiente';

export interface ColaboradorResumen {
  id: string;
  nombre: string;
  cargo: string;
  area: string;
  usuario: string;
  estado: EstadoColaborador;
  intentos: number;
}

/**
 * Roster único de colaboradores de la empresa demo (Vertice Consulting):
 * fuente compartida entre el directorio, el panel general y el detalle por
 * colaborador, para que los mismos IDs y datos aparezcan en las tres vistas
 * en vez de tres listas hardcodeadas que podían divergir.
 */
export const COLABORADORES: ColaboradorResumen[] = [
  { id: '1', nombre: 'Marcos Iñiguez', cargo: 'Analista financiero', area: 'Contabilidad', usuario: 'miniguez', estado: 'activo', intentos: 9 },
  { id: '2', nombre: 'Renata Sotomayor', cargo: 'Diseñadora de producto', area: 'Marketing', usuario: 'rsotomayor', estado: 'pendiente', intentos: 0 },
  { id: '3', nombre: 'Tobías Fuentes', cargo: 'Backend engineer', area: 'Ingeniería', usuario: 'tfuentes', estado: 'activo', intentos: 2 },
  { id: '4', nombre: 'Camila Ordóñez', cargo: 'Contadora senior', area: 'Contabilidad', usuario: 'cordonez', estado: 'activo', intentos: 6 },
  { id: '5', nombre: 'Ismael Vega', cargo: 'Growth marketer', area: 'Marketing', usuario: 'ivega', estado: 'activo', intentos: 3 },
  { id: '6', nombre: 'Valentina Rojas', cargo: 'Frontend engineer', area: 'Ingeniería', usuario: 'vrojas', estado: 'activo', intentos: 0 },
  { id: '7', nombre: 'Joaquín Herrera', cargo: 'DevOps engineer', area: 'Ingeniería', usuario: 'jherrera', estado: 'activo', intentos: 1 },
  { id: '8', nombre: 'Fernanda Lagos', cargo: 'Abogada corporativa', area: 'Legal', usuario: 'flagos', estado: 'activo', intentos: 0 },
  { id: '9', nombre: 'Cristóbal Muñoz', cargo: 'Data engineer', area: 'Ingeniería', usuario: 'cmunoz', estado: 'activo', intentos: 4 },
  { id: '10', nombre: 'Bárbara Concha', cargo: 'Reclutadora', area: 'RR.HH.', usuario: 'bconcha', estado: 'pendiente', intentos: 0 },
];
