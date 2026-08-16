# Los indicadores del tablero

Qué mide cada número de `/tablero/`, con qué fórmula y qué deja por fuera. Es la
página que un auditor va a cuestionar, así que acá está escrito lo que un
supervisor puede verificar con calculadora contra el escenario de las pruebas
(`apps/kpis/tests/scenario.py`).

Las consultas viven en [`apps/kpis/queries.py`](../apps/kpis/queries.py): SQL crudo
escrito a mano, una consulta por indicador, todos los valores como parámetros
ligados (`%s`) y `company_id = %s` en el WHERE de todas. La aritmética la hace
Postgres; Python solo arma la tabla «por equipo» juntando dos resultados por
`asset_id`.

## Reglas que comparten los seis

| Regla | Por qué |
|---|---|
| Una OT entra en la ventana por **`finished_at`** (cuándo se cerró), salvo el cumplimiento y el backlog, que van por **`due_date`** | El cumplimiento pregunta por el *plan*, no por la ejecución: una preventiva programada y nunca hecha tiene que pesar |
| Las OTs **canceladas nunca cuentan**, en ningún indicador | Una OT cancelada no es trabajo hecho ni trabajo pendiente |
| La **parada es parada**, la haya causado un correctivo o un preventivo | Así disponibilidad y MTBF no pueden discrepar sobre cuánto estuvo quieta la máquina |
| Solo los **correctivos** cuentan como falla | Un preventivo programado no es una falla |
| La ventana **nunca llega al futuro**: «mes actual» termina *ahora*, no el 31 | Una preventiva que vence la otra semana todavía no incumplió nada |
| Los equipos **dados de baja** no entran en la flota (disponibilidad y MTBF), pero el trabajo que se les hizo sí cuenta en MTTR, costo y backlog | Una máquina que ya no está en planta no puede estar disponible ni indisponible; la reparación que se le hizo el mes pasado, en cambio, sí ocurrió y sí costó plata |
| Toda razón divide con **`NULLIF(…, 0)`** | Sin fallas, sin preventivas o sin equipos el indicador es «—» (no hay dato), nunca un error 500 ni un 0 que se lee como «perfecto» |
| Las fechas se comparan en **America/Bogotá** | Una OT cerrada a las 20:00 en Bogotá es la 1:00 UTC del día siguiente: en UTC se leería como cerrada tarde |

El selector de período ofrece **mes actual · últimos 30 días · últimos 90 días ·
año en curso** (por defecto 30 días) y el filtro de sede es opcional. Ambos viajan
como parámetros ligados; el período nunca se interpola en el SQL.

## 1. Disponibilidad

> (minutos del período − minutos de parada) ÷ minutos del período · 100

Por equipo y de la flota. La parada sale de `downtime_minutes`, tal como la
registró el técnico al terminar la OT. Es **tiempo calendario**, no tiempo de
turno: el producto todavía no conoce los turnos de la planta e inventarlos haría
el número imposible de auditar. Una parada mayor que la ventana (dato mal
digitado) se recorta en 0 %, nunca en un porcentaje negativo.

Flota = suma de operación de todos los equipos ÷ suma de calendario de todos los
equipos — no el promedio de los porcentajes, que le daría el mismo peso a una
máquina crítica y a una que casi no se usa.

## 2. Cumplimiento del plan preventivo

> preventivas cerradas a tiempo ÷ preventivas programadas en el período · 100

«Cerrada a tiempo» = estado `terminada` o `verificada` **y** `finished_at` (en
hora de Bogotá) menor o igual a `due_date`. El denominador son las preventivas
cuyo `due_date` cae en el período, hechas o no: una preventiva que nadie tocó
baja el cumplimiento, que es justamente lo que el indicador debe mostrar.
Sin preventivas programadas: «—», no 0 %.

## 3. MTBF (tiempo medio entre fallas)

> horas de operación ÷ número de fallas

Horas de operación = calendario del período − parada registrada. Por equipo y de
la flota (operación total ÷ fallas totales, no el promedio de los MTBF).
Un equipo sin fallas no tiene MTBF: es «—», no infinito y no cero.

## 4. MTTR (tiempo medio de reparación)

> promedio de (`finished_at` − `started_at`) sobre las correctivas cerradas en el período

Las OTs sin ambas marcas de tiempo quedan fuera: no son reparaciones de duración
desconocida, son reparaciones cuya duración nadie registró, y promediarlas como
cero maquillaría el número.

## 5. Backlog vencido

> OTs abiertas (`abierta`, `asignada`, `en_progreso`) con `due_date` anterior a hoy

Es el único indicador que **ignora el selector de período**: una OT que venció
hace tres meses y sigue abierta es backlog *hoy*, sin importar qué ventana esté
mirando la pantalla. Se reparte en tres baldes por antigüedad —
**menos de 7 días · de 7 a 30 · más de 30** — y la tabla lista las más viejas
primero, con el equipo y los días de atraso. Una OT cerrada tarde no es backlog:
eso lo castiga el cumplimiento.

## 6. Costo por equipo y mes

> mano de obra + repuestos de las OTs cerradas en el período, agrupado por equipo y mes calendario

Ranking por total, top 10. El mes se calcula en hora de Bogotá (una OT cerrada a
las 19:00 del 31 pertenece a ese mes, no al siguiente en UTC). La tarjeta muestra
el total del período completo, no la suma de las diez filas visibles: sale de la
misma consulta con `SUM(…) OVER ()`, que se calcula antes del `LIMIT`, así que
tabla y total no pueden discrepar. Sin costos cargados: $0 — nadie gastó nada, y
eso sí es un número.

## Lo que el tablero no hace todavía

- No hay gráficas: seis valores actuales son tarjetas, y una tabla de datos vale
  más que un `chart.js` a medias en un teléfono de planta.
- No hay exportación a Excel ni matriz anual de programación (fase 2).
- No hay analítica entre empresas: un administrador de plataforma no tiene
  `company_id` propio, así que el tablero le responde 403 en vez de inventar uno.
