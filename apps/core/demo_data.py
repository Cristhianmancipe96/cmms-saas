"""The demo company, as data. Every string in this file is invented.

CLAUDE.md's habeas-data rule (Ley 1581) is not "be careful with the seeds": it
is that no real customer's name, NIT, address, phone or email may ever enter
this repository. Keeping the whole catalogue in one module — literals only, no
logic — is what makes that rule checkable instead of trusted:
`apps/core/tests/test_demo_data.py` reads this file as text and refuses any
address outside `example.com` (RFC 2606 reserves it precisely so it can never
be somebody's real inbox) and any of the free-mail domains a real person's
address would almost certainly carry.

"Empaques La Sabana S.A.S." is an invented flexible-packaging plant: three
flow-pack wrappers, a screw compressor, two conveyors and a bag sealer, split
across a plant in Funza and a warehouse in Fontibón. It exists because a demo
of a maintenance system with three rows in it demonstrates nothing — the
dashboard needs history to have numbers, and the backlog needs work orders of
different ages to have a shape.

The writing side lives in `apps/core/management/commands/seed_demo.py`. This
module never touches the database.
"""

from decimal import Decimal

# --- The company ------------------------------------------------------------

COMPANY_NAME = "Empaques La Sabana S.A.S."
# Invented. Colombian NITs are nine digits plus a check digit; this one belongs
# to nobody — the range is not assigned to any real company we deal with, and
# the seed refuses to run against a production database anyway.
COMPANY_NIT = "901555010-7"

SUBSCRIPTION = {
    "plan": "standard",
    "status": "active",
    # Room to invite one more person during the demo without hitting the seat
    # limit — the invitation screen is part of the script.
    "max_users": 10,
    "max_assets": 50,
    "period_days": 365,
}

# --- Sites ------------------------------------------------------------------

PLANTA = "Planta Funza"
BODEGA = "Bodega Fontibón"

SITES: tuple[dict, ...] = (
    {"name": PLANTA, "address": "Parque Industrial Portos, Funza, Cundinamarca"},
    {"name": BODEGA, "address": "Calle 13 con Carrera 96, Fontibón, Bogotá"},
)

# --- People -----------------------------------------------------------------
#
# Usernames are prefixed `sabana.` so they cannot collide with the ad-hoc demo
# accounts an earlier brief left in a shared development database — a
# `get_or_create` that matched one of those would quietly adopt another
# company's user. The command refuses that case out loud instead.
#
# No passwords here. They are generated per run with `secrets` and printed once
# to the console: a password in the repository is a password in every clone of
# it, and this file is public.

USERS: tuple[dict, ...] = (
    {
        "username": "sabana.admin",
        "role": "admin",
        "first_name": "Marcela",
        "last_name": "Ruiz",
        "email": "sabana.admin@example.com",
        "whatsapp_phone": "+57 300 000 0011",
    },
    {
        "username": "sabana.super",
        "role": "supervisor",
        "first_name": "Julián",
        "last_name": "Ochoa",
        "email": "sabana.super@example.com",
        "whatsapp_phone": "+57 300 000 0012",
    },
    {
        "username": "sabana.tecnico",
        "role": "technician",
        "first_name": "Andrés",
        "last_name": "Beltrán",
        "email": "sabana.tecnico@example.com",
        "whatsapp_phone": "+57 300 000 0013",
    },
    {
        "username": "sabana.oficina",
        "role": "staff",
        "first_name": "Paula",
        "last_name": "Nieto",
        "email": "sabana.oficina@example.com",
        "whatsapp_phone": "+57 300 000 0014",
    },
)

ADMIN = USERS[0]["username"]
SUPERVISOR = USERS[1]["username"]
TECHNICIAN = USERS[2]["username"]
STAFF = USERS[3]["username"]

# --- Equipment --------------------------------------------------------------

CAT_EMPACADORA = "Empacadora flow-pack"
CAT_COMPRESOR = "Compresor"
CAT_BANDA = "Banda transportadora"
CAT_SELLADORA = "Selladora"

CATEGORIES: tuple[str, ...] = (CAT_EMPACADORA, CAT_COMPRESOR, CAT_BANDA, CAT_SELLADORA)


def _flowpac_specs(line: str, packages_per_minute: int) -> list[dict[str, str]]:
    """The technical sheet of a flow-pack wrapper, as the JSONB field stores it.

    Same keys on all three machines and different values, on purpose: that is
    what an equipment list looks like in a real plant, and it is what makes the
    "ficha técnica" panel of the demo look like a record rather than a mock-up.
    """
    return [
        {"key": "Velocidad máxima", "value": f"{packages_per_minute} paquetes/min"},
        {"key": "Ancho de bobina", "value": "420 mm"},
        {"key": "Voltaje", "value": "220 V trifásico"},
        {"key": "Potencia instalada", "value": "5,5 kW"},
        {"key": "Presión de aire", "value": "6 bar"},
        {"key": "Temperatura de mordaza", "value": "160 °C"},
        {"key": "Línea", "value": line},
    ]


ASSETS: tuple[dict, ...] = (
    {
        "code": "FLW-01",
        "name": "Empacadora Flowpac línea 1",
        "category": CAT_EMPACADORA,
        "site": PLANTA,
        "brand": "Sabana Pack",
        "model": "SP-450",
        "serial_number": "SP450-2021-0114",
        "criticality": "alta",
        "status": "operativo",
        "location_detail": "Línea 1, costado norte",
        "purchase_years_ago": 4,
        "specs": _flowpac_specs("Línea 1", 120),
    },
    {
        "code": "FLW-02",
        "name": "Empacadora Flowpac línea 2",
        "category": CAT_EMPACADORA,
        "site": PLANTA,
        "brand": "Sabana Pack",
        "model": "SP-450",
        "serial_number": "SP450-2021-0119",
        "criticality": "alta",
        "status": "operativo",
        "location_detail": "Línea 2, costado norte",
        "purchase_years_ago": 4,
        "specs": _flowpac_specs("Línea 2", 120),
    },
    {
        "code": "FLW-03",
        "name": "Empacadora Flowpac línea 3",
        "category": CAT_EMPACADORA,
        "site": PLANTA,
        "brand": "Sabana Pack",
        "model": "SP-600",
        "serial_number": "SP600-2023-0042",
        "criticality": "media",
        "status": "operativo",
        "location_detail": "Línea 3, junto a despacho",
        "purchase_years_ago": 2,
        "specs": _flowpac_specs("Línea 3", 160),
    },
    {
        "code": "CMP-01",
        "name": "Compresor de tornillo 30 HP",
        "category": CAT_COMPRESOR,
        "site": PLANTA,
        "brand": "Airtec",
        "model": "AT-30S",
        "serial_number": "AT30S-2019-0771",
        "criticality": "alta",
        "status": "operativo",
        "location_detail": "Cuarto de compresores",
        "purchase_years_ago": 6,
        "specs": [
            {"key": "Potencia", "value": "30 HP"},
            {"key": "Caudal", "value": "120 CFM"},
            {"key": "Presión de trabajo", "value": "8 bar"},
            {"key": "Voltaje", "value": "440 V trifásico"},
            {"key": "Tipo de aceite", "value": "Sintético ISO VG 46"},
        ],
    },
    {
        "code": "BND-01",
        "name": "Banda transportadora de entrada",
        "category": CAT_BANDA,
        "site": PLANTA,
        "brand": "Transveyor",
        "model": "TV-8",
        "serial_number": "TV8-2020-0308",
        "criticality": "media",
        "status": "operativo",
        "location_detail": "Recepción de producto",
        "purchase_years_ago": 5,
        "specs": [
            {"key": "Longitud", "value": "8 m"},
            {"key": "Ancho de banda", "value": "600 mm"},
            {"key": "Velocidad", "value": "0,4 m/s"},
            {"key": "Motorreductor", "value": "1,5 kW"},
        ],
    },
    {
        "code": "BND-02",
        "name": "Banda transportadora de despacho",
        "category": CAT_BANDA,
        "site": BODEGA,
        "brand": "Transveyor",
        "model": "TV-12",
        "serial_number": "TV12-2022-0517",
        "criticality": "baja",
        "status": "operativo",
        "location_detail": "Muelle de cargue 2",
        "purchase_years_ago": 3,
        "specs": [
            {"key": "Longitud", "value": "12 m"},
            {"key": "Ancho de banda", "value": "800 mm"},
            {"key": "Velocidad", "value": "0,6 m/s"},
            {"key": "Motorreductor", "value": "2,2 kW"},
        ],
    },
    {
        "code": "SLL-01",
        "name": "Selladora de bolsas",
        "category": CAT_SELLADORA,
        "site": BODEGA,
        "brand": "Termosell",
        "model": "TS-300",
        "serial_number": "TS300-2021-0093",
        "criticality": "media",
        "status": "operativo",
        "location_detail": "Zona de reempaque",
        "purchase_years_ago": 4,
        "specs": [
            {"key": "Ancho de sellado", "value": "300 mm"},
            {"key": "Temperatura máxima", "value": "220 °C"},
            {"key": "Voltaje", "value": "110 V"},
        ],
    },
    {
        "code": "FLW-00",
        "name": "Empacadora Flowpac línea 0 (retirada)",
        "category": CAT_EMPACADORA,
        "site": PLANTA,
        "brand": "Sabana Pack",
        "model": "SP-300",
        "serial_number": "SP300-2012-0007",
        "criticality": "baja",
        "status": "dado_de_baja",
        "location_detail": "Bodega de repuestos",
        "purchase_years_ago": 13,
        "baja_reason": (
            "Reemplazada por la línea 3 en 2023. Se conservan repuestos "
            "aprovechables del cabezal."
        ),
        "specs": [
            {"key": "Velocidad máxima", "value": "70 paquetes/min"},
            {"key": "Voltaje", "value": "220 V trifásico"},
        ],
    },
)

# --- Checklist templates ----------------------------------------------------
#
# `item_type` "numeric" items carry a unit and a range, and the work-order
# service decides OK/Falla from the measurement itself — the technician records
# what the gauge says, not what they think of it.

CHK_SEMANAL = "Flowpac — inspección semanal"
CHK_MENSUAL = "Flowpac — mantenimiento mensual"
CHK_COMPRESOR = "Compresor — rutina de 250 h"

CHECKLISTS: tuple[dict, ...] = (
    {
        "name": CHK_SEMANAL,
        "category": CAT_EMPACADORA,
        "items": (
            {"text": "Limpieza general de la máquina", "item_type": "check"},
            {"text": "Estado de la banda de arrastre", "item_type": "check"},
            {"text": "Cuchilla de corte sin filo mellado", "item_type": "check"},
            {
                "text": "Presión de aire en la línea",
                "item_type": "numeric",
                "unit": "bar",
                "min_value": Decimal("5.00"),
                "max_value": Decimal("7.00"),
            },
            {"text": "Fugas de aire audibles", "item_type": "check"},
            {
                "text": "Temperatura de la mordaza de sellado",
                "item_type": "numeric",
                "unit": "°C",
                "min_value": Decimal("150.00"),
                "max_value": Decimal("175.00"),
            },
            {"text": "Paro de emergencia responde", "item_type": "check"},
            {
                "text": "Observaciones del operario",
                "item_type": "text",
                "required": False,
            },
        ),
    },
    {
        "name": CHK_MENSUAL,
        "category": CAT_EMPACADORA,
        "items": (
            {"text": "Limpieza profunda del cabezal", "item_type": "check"},
            {"text": "Lubricación de cadenas y guías", "item_type": "check"},
            {"text": "Ajuste de tensión de la banda", "item_type": "check"},
            {"text": "Revisión de rodamientos del eje principal", "item_type": "check"},
            {"text": "Estado de las resistencias de sellado", "item_type": "check"},
            {
                "text": "Consumo de corriente del motor principal",
                "item_type": "numeric",
                "unit": "A",
                "min_value": Decimal("8.00"),
                "max_value": Decimal("14.00"),
            },
            {"text": "Revisión de mangueras neumáticas", "item_type": "check"},
            {"text": "Estado del tablero eléctrico", "item_type": "check"},
            {"text": "Prueba de sensores fotoeléctricos", "item_type": "check"},
            {
                "text": "Nivel de ruido en operación",
                "item_type": "numeric",
                "unit": "dB",
                "min_value": Decimal("60.00"),
                "max_value": Decimal("85.00"),
            },
            {"text": "Guardas y protecciones completas", "item_type": "check"},
            {"text": "Repuestos usados", "item_type": "text", "required": False},
        ),
    },
    {
        "name": CHK_COMPRESOR,
        "category": CAT_COMPRESOR,
        "items": (
            {"text": "Cambio de filtro de aire", "item_type": "check"},
            {"text": "Revisión de nivel de aceite", "item_type": "check"},
            {"text": "Purga del tanque de condensados", "item_type": "check"},
            {
                "text": "Presión de descarga",
                "item_type": "numeric",
                "unit": "bar",
                "min_value": Decimal("7.00"),
                "max_value": Decimal("9.00"),
            },
            {"text": "Estado de correas", "item_type": "check"},
            {"text": "Observaciones", "item_type": "text", "required": False},
        ),
    },
)

# --- Maintenance plans ------------------------------------------------------
#
# `forgotten_days_ago` is what gives the backlog its shape. The occurrence of
# this plan closest to that many days ago is left open instead of closed, so
# the dashboard's ageing buckets («menos de 7», «entre 7 y 30», «más de 30»)
# each have something in them — a backlog table where every row is three days
# old teaches a viewer nothing about what the screen is for.

PLANS: tuple[dict, ...] = (
    {
        "asset": "FLW-01",
        "name": "Preventivo semanal línea 1",
        "kind": "preventivo",
        "frequency_type": "calendar",
        "interval_days": 7,
        "checklist": CHK_SEMANAL,
        "estimated_minutes": 45,
        # Between 7 and 30 days late — the middle backlog bucket.
        "forgotten_days_ago": 12,
    },
    {
        "asset": "FLW-02",
        "name": "Preventivo semanal línea 2",
        "kind": "preventivo",
        "frequency_type": "calendar",
        "interval_days": 7,
        "checklist": CHK_SEMANAL,
        "estimated_minutes": 45,
        # More than 30 days late — the bucket the dashboard paints red.
        "forgotten_days_ago": 40,
    },
    {
        "asset": "FLW-03",
        "name": "Inspección semanal línea 3",
        # `inspeccion` produces work orders of type «Inspección», which the PM
        # compliance indicator deliberately does not count (it measures the
        # preventive plan). One plan of this kind is here so the demo shows
        # that distinction instead of implying every plan is the same thing.
        "kind": "inspeccion",
        "frequency_type": "calendar",
        "interval_days": 7,
        "checklist": CHK_SEMANAL,
        "estimated_minutes": 30,
        # Less than 7 days late — the youngest backlog bucket.
        "forgotten_days_ago": 5,
    },
    {
        "asset": "FLW-01",
        "name": "Mantenimiento mensual línea 1",
        "kind": "preventivo",
        "frequency_type": "calendar",
        "interval_days": 30,
        "checklist": CHK_MENSUAL,
        "estimated_minutes": 180,
        "forgotten_days_ago": None,
    },
    {
        "asset": "BND-01",
        "name": "Lubricación quincenal de la banda de entrada",
        "kind": "lubricacion",
        "frequency_type": "calendar",
        "interval_days": 15,
        "checklist": None,
        "estimated_minutes": 30,
        "forgotten_days_ago": 45,
    },
    {
        "asset": "SLL-01",
        "name": "Calibración trimestral de la selladora",
        "kind": "calibracion",
        "frequency_type": "calendar",
        "interval_days": 90,
        "checklist": None,
        "estimated_minutes": 90,
        "forgotten_days_ago": None,
    },
    {
        "asset": "CMP-01",
        "name": "Rutina del compresor cada 250 h",
        "kind": "preventivo",
        "frequency_type": "meter",
        "meter_interval_hours": Decimal("250.00"),
        "checklist": CHK_COMPRESOR,
        "estimated_minutes": 120,
        # Meter plans have no calendar occurrences: their two historical work
        # orders are written explicitly in METER_WORK_ORDERS below.
        "forgotten_days_ago": None,
    },
)

# How far back the history goes.
HISTORY_DAYS = 90
# Work orders are also generated for the week ahead, so «Mis OTs» has something
# under "Para hoy" and "Próximas" the moment the demo starts.
HORIZON_DAYS = 7
# One in every LATE_EVERY closed preventive work orders was finished after its
# due date. Together with the four plans left deliberately overdue, this puts
# PM compliance in the low eighties — a believable plant, and inside the
# 60–95 % band the smoke test asserts.
LATE_EVERY = 8
LATE_BY_DAYS = 4

# What a closed preventive work order records. Fixed numbers rather than random
# ones: a seed that produces a different dashboard on every run is a seed you
# cannot write a test against.
PREVENTIVE_DOWNTIME_MINUTES = (25, 40, 55, 30, 45)
PREVENTIVE_LABOR_COP = (60_000, 85_000, 110_000)
PREVENTIVE_PARTS_COP = (0, 45_000, 120_000, 0, 90_000)

PREVENTIVE_WORK_DONE = (
    "Rutina ejecutada según el checklist. Sin novedades relevantes.",
    "Se ejecutó la rutina completa y se ajustó la tensión de la banda.",
    "Rutina ejecutada. Se reportó desgaste leve en la cuchilla para seguimiento.",
)

# --- Corrective history -----------------------------------------------------
#
# Six breakdowns spread over the window. These are what MTBF, MTTR and the cost
# table are computed from, so their downtime and their repair duration are the
# numbers the dashboard shows.

CORRECTIVE_WORK_ORDERS: tuple[dict, ...] = (
    {
        "asset": "FLW-01",
        "days_ago": 78,
        "priority": "alta",
        "failure_description": "La mordaza de sellado dejó de calentar a media producción.",
        "work_done": "Se cambió la resistencia de la mordaza y se recalibró el termostato.",
        "downtime_minutes": 210,
        "repair_hours": 3,
        "labor_cost_cop": 180_000,
        "parts_cost_cop": 320_000,
    },
    {
        "asset": "CMP-01",
        "days_ago": 61,
        "priority": "critica",
        "failure_description": "El compresor se apagó por alta temperatura y no volvió a arrancar.",
        "work_done": "Se limpió el radiador de aceite y se reemplazó el sensor de temperatura.",
        "downtime_minutes": 320,
        "repair_hours": 5,
        "labor_cost_cop": 260_000,
        "parts_cost_cop": 540_000,
    },
    {
        "asset": "BND-01",
        "days_ago": 44,
        "priority": "media",
        "failure_description": "La banda patina al arrancar con carga.",
        "work_done": "Se tensionó la banda y se cambió el rodillo tensor.",
        "downtime_minutes": 95,
        "repair_hours": 2,
        "labor_cost_cop": 90_000,
        "parts_cost_cop": 150_000,
    },
    {
        "asset": "FLW-02",
        "days_ago": 27,
        "priority": "alta",
        "failure_description": "Corte irregular: la cuchilla deja el paquete abierto.",
        "work_done": "Se afiló y realineó la cuchilla; se ajustó el sincronismo del cabezal.",
        "downtime_minutes": 140,
        "repair_hours": 2,
        "labor_cost_cop": 120_000,
        "parts_cost_cop": 80_000,
    },
    {
        "asset": "SLL-01",
        "days_ago": 16,
        "priority": "media",
        "failure_description": "La selladora quema la bolsa en el borde derecho.",
        "work_done": "Se reemplazó la cinta de teflón y se niveló la barra de sellado.",
        "downtime_minutes": 70,
        "repair_hours": 1,
        "labor_cost_cop": 60_000,
        "parts_cost_cop": 35_000,
    },
    {
        "asset": "FLW-03",
        "days_ago": 6,
        "priority": "alta",
        "failure_description": "Ruido metálico en el eje principal y vibración fuerte.",
        "work_done": "Se cambió el rodamiento del eje principal y se lubricó la cadena.",
        "downtime_minutes": 260,
        "repair_hours": 4,
        "labor_cost_cop": 200_000,
        "parts_cost_cop": 610_000,
    },
)

# --- The compressor's hour meter --------------------------------------------
#
# Roughly 12 hours of use a day, read every nine days. The last reading sits
# ~216 h above the baseline of the 250 h plan — just under one interval — so
# entering one more reading during the demo is what makes the scheduler produce
# a work order on the spot.

METER_START_HOURS = Decimal("18400.00")
METER_READING_EVERY_DAYS = 9
METER_HOURS_PER_DAY = Decimal("12.00")

# The two historical routines of the meter plan, and the meter value each was
# based on. `hours_at_last_generated_wo` ends up at the second one.
METER_WORK_ORDERS: tuple[dict, ...] = (
    {"days_ago": 72, "work_done": "Rutina de 250 h: filtro de aire y purga de condensados."},
    {"days_ago": 22, "work_done": "Rutina de 250 h: cambio de filtro y revisión de correas."},
)

# --- Pending failure reports ------------------------------------------------

REQUESTS: tuple[dict, ...] = (
    {
        "asset": "BND-02",
        "days_ago": 2,
        "reporter": STAFF,
        "description": (
            "La banda de despacho se detiene sola cada tanto y toca volver a "
            "darle arranque desde el tablero."
        ),
    },
    {
        "asset": "FLW-03",
        "days_ago": 1,
        "reporter": STAFF,
        "description": (
            "La línea 3 está dejando paquetes con el sellado flojo desde el "
            "turno de la mañana."
        ),
    },
)
