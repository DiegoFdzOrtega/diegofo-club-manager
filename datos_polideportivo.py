"""
datos_polideportivo.py — Genera un polideportivo de demostración con datos INVENTADOS.

Unos 140 socios repartidos en grupos de fútbol, natación, pádel y atletismo, con
cuotas de la temporada, reservas de pistas, pedidos de equipaciones y movimientos
de caja de los días anteriores, para que la aplicación parezca un centro real.

Los nombres, DNI, IBAN, teléfonos y direcciones son de mentira: se generan al azar
(con una semilla fija, así siempre salen los mismos) y solo tienen la letra y los
dígitos de control correctos para pasar las validaciones.
"""

import random
from datetime import date, timedelta

from datos_ejemplo import dni_de_prueba, iban_de_prueba
from modelos import (HORA_APERTURA, HORA_CIERRE, Cuota, Equipo, Instalacion, Movimiento, Pedido, Producto, Reserva,
                     Socio, Tarifa, categoria_por_edad)

azar = random.Random(2026)
HOY = date.today()

NOMBRES_H = ["Hugo", "Mateo", "Martín", "Lucas", "Leo", "Daniel", "Alejandro", "Pablo", "Manuel", "Álvaro",
             "Adrián", "Mario", "Diego", "Javier", "Marcos", "Iker", "Bruno", "Nicolás", "Sergio", "Pau",
             "Jorge", "Carlos", "Raúl", "Vicente", "Toni", "Joan", "Andreu", "Rubén", "Héctor", "Gonzalo"]
NOMBRES_M = ["Lucía", "Sofía", "Martina", "María", "Julia", "Paula", "Valeria", "Emma", "Daniela", "Carla",
             "Alba", "Noa", "Nora", "Sara", "Laura", "Marta", "Elena", "Ana", "Clara", "Irene",
             "Carmen", "Rosa", "Pilar", "Inés", "Neus", "Aitana", "Vega", "Lola", "Olivia", "Candela"]
APELLIDOS = ["García", "Martínez", "López", "Sánchez", "Pérez", "Gómez", "Martín", "Ruiz", "Hernández", "Díaz",
             "Moreno", "Muñoz", "Álvarez", "Romero", "Navarro", "Torres", "Domínguez", "Gil", "Vidal", "Ferrer",
             "Soler", "Peris", "Llorens", "Cano", "Ibáñez", "Ortega", "Sanz", "Marí", "Bosch", "Climent",
             "Gimeno", "Montesinos", "Puig", "Roig", "Server", "Tormo", "Vila", "Albert", "Esteve", "Pastor"]
CALLES = ["C/ Mayor", "C/ San Vicente", "Av. del Mar", "C/ Valencia", "C/ de la Huerta", "Av. Diputación",
          "C/ Doctor Fleming", "C/ Colón", "Pl. del Ayuntamiento", "C/ Sant Josep", "Av. Constitución"]
PUEBLOS = ["Valencia", "Bétera", "Burjassot", "Godella", "Paterna", "Moncada", "Rocafort", "Massamagrell"]
BANCOS = ["2100", "0049", "0182", "0081", "2038", "3058", "0128", "1465"]  # códigos de entidad (cuentas inventadas)


def nombre_al_azar(mujer=None):
    mujer = azar.random() < 0.45 if mujer is None else mujer
    nombre = azar.choice(NOMBRES_M if mujer else NOMBRES_H)
    return f"{nombre} {azar.choice(APELLIDOS)} {azar.choice(APELLIDOS)}"


def fecha_nacimiento(edad_min, edad_max):
    edad = azar.randint(edad_min, edad_max)
    cumple = date(HOY.year - edad, HOY.month, min(HOY.day, 28))  # día 28 como mucho: así no falla el 29 de febrero
    nacimiento = cumple - timedelta(days=azar.randint(1, 330))
    return nacimiento.isoformat()


def telefono():
    return f"6{azar.randint(0, 99):02d} {azar.randint(0, 999):03d} {azar.randint(0, 999):03d}"


def iban_al_azar():
    cuenta = azar.choice(BANCOS) + f"{azar.randint(0, 9999):04d}" + f"{azar.randint(0, 99):02d}" + f"{azar.randint(0, 10**10 - 1):010d}"
    return iban_de_prueba(cuenta)


def sin_tildes(texto):
    return texto.translate(str.maketrans("áéíóúüñÁÉÍÓÚÑ", "aeiouunAEIOUN"))


# ---------------------------------------------------------------------------
# Tarifas, grupos e instalaciones
# ---------------------------------------------------------------------------

def crear_tarifas():
    return {
        "escuela": Tarifa(nombre="Fútbol escuela", importe=30, descripcion="Prebenjamín, benjamín y alevín (fútbol 7)"),
        "federado": Tarifa(nombre="Fútbol federado", importe=50, descripcion="Infantil a juvenil (fútbol 11, ficha federativa)"),
        "senior": Tarifa(nombre="Senior Premium", importe=100, descripcion="Senior y veteranos con fisioterapia y gimnasio"),
        "nat_inf": Tarifa(nombre="Natación infantil", importe=35, descripcion="Cursillos de 2 días por semana"),
        "nat_adu": Tarifa(nombre="Natación adultos", importe=40, descripcion="Adultos y máster"),
        "aquagym": Tarifa(nombre="Aquagym", importe=25, descripcion="2 sesiones por semana"),
        "padel": Tarifa(nombre="Escuela de pádel", importe=45, descripcion="Grupos de 4 alumnos"),
        "atletismo": Tarifa(nombre="Atletismo", importe=25, descripcion="Escuela de atletismo"),
    }


# nombre, deporte, categoría, horario, entrenador, tarifa, plazas, (edad mín, edad máx), socios que se generan
GRUPOS = [
    ("Prebenjamín", "Fútbol", "Prebenjamín", "L-X 17:30-18:30", "Andrés Mora", "escuela", 16, (6, 7), 13),
    ("Benjamín A", "Fútbol", "Benjamín", "L-X 18:30-19:45", "Clara Gimeno", "escuela", 16, (8, 9), 14),
    ("Alevín A", "Fútbol", "Alevín", "M-J 17:30-19:00", "Rosa Gil", "escuela", 16, (10, 11), 14),
    ("Alevín B", "Fútbol", "Alevín", "M-J 17:30-19:00", "Iván Roig", "escuela", 16, (10, 11), 11),
    ("Infantil A", "Fútbol", "Infantil", "L-X-V 18:00-19:30", "Toni Vidal", "federado", 22, (12, 13), 18),
    ("Cadete A", "Fútbol", "Cadete", "L-X-V 19:30-21:00", "Sergio Puig", "federado", 22, (14, 15), 17),
    ("Juvenil A", "Fútbol", "Juvenil", "M-J-V 19:30-21:00", "Pepe Albert", "federado", 24, (16, 18), 16),
    ("Senior A", "Fútbol", "Senior", "M-J 21:00-22:30", "Paco Ferrer", "senior", 25, (19, 32), 18),
    ("Veteranos", "Fútbol", "Senior", "V 21:00-22:30", "Paco Ferrer", "senior", 0, (35, 52), 8),
    ("Natación Bebés", "Natación", "Escuela", "S 10:00-10:45", "Marta Climent", "nat_inf", 8, (3, 5), 8),
    ("Natación Iniciación", "Natación", "Iniciación", "L-X 17:30-18:15", "Marta Climent", "nat_inf", 14, (6, 10), 12),
    ("Natación Perfeccionamiento", "Natación", "Perfeccionamiento", "M-J 18:15-19:15", "Neus Bosch", "nat_inf", 14, (11, 16), 10),
    ("Natación Adultos", "Natación", "Adultos", "L-X 20:00-21:00", "Neus Bosch", "nat_adu", 16, (25, 60), 9),
    ("Natación Máster", "Natación", "Máster", "M-J 07:00-08:00", "Neus Bosch", "nat_adu", 12, (28, 55), 6),
    ("Aquagym", "Natación", "Adultos", "M-J 10:00-11:00", "Lola Esteve", "aquagym", 20, (45, 75), 14),
    ("Escuela de pádel", "Pádel", "Adultos", "L-X 19:00-20:30", "Jorge Tormo", "padel", 8, (18, 55), 7),
    ("Atletismo Base", "Atletismo", "Iniciación", "M-J 17:30-19:00", "Elena Server", "atletismo", 20, (8, 14), 11),
]


def crear_instalaciones():
    return [
        Instalacion(nombre="Fútbol 11", deporte="Fútbol", precio_socio=60, precio_no_socio=90),
        Instalacion(nombre="Fútbol 7 A", deporte="Fútbol", precio_socio=30, precio_no_socio=50),
        Instalacion(nombre="Fútbol 7 B", deporte="Fútbol", precio_socio=30, precio_no_socio=50),
        Instalacion(nombre="Tenis 1", deporte="Tenis", precio_socio=8, precio_no_socio=14),
        Instalacion(nombre="Tenis 2", deporte="Tenis", precio_socio=8, precio_no_socio=14),
        Instalacion(nombre="Pádel 1", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pádel 2", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pádel 3", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pádel 4", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pista de atletismo", deporte="Atletismo", precio_socio=3, precio_no_socio=6),
    ]


def crear_productos():
    return [
        Producto(nombre="Camiseta oficial", precio=35, tallas="6,8,10,12,14,S,M,L,XL,XXL", stock=64),
        Producto(nombre="Pantalón oficial", precio=20, tallas="6,8,10,12,14,S,M,L,XL,XXL", stock=70),
        Producto(nombre="Medias", precio=8, tallas="Única", stock=110),
        Producto(nombre="Segunda equipación", precio=45, tallas="6,8,10,12,14,S,M,L,XL", stock=22),
        Producto(nombre="Chándal de paseo", precio=55, tallas="8,10,12,14,S,M,L,XL", stock=18),
        Producto(nombre="Gorro de natación", precio=9, tallas="Infantil,Adulto", stock=45),
        Producto(nombre="Bañador del club", precio=28, tallas="6,8,10,12,14,S,M,L", stock=4),
        Producto(nombre="Mochila del club", precio=25, tallas="Única", stock=3),
    ]


# ---------------------------------------------------------------------------
# Todo junto
# ---------------------------------------------------------------------------

def meses_de_temporada():
    """Septiembre de esta temporada hasta el mes actual: ['2026-09', '2026-10', '2026-11']."""
    inicio = date(HOY.year if HOY.month >= 9 else HOY.year - 1, 9, 1)
    meses, d = [], inicio
    while d <= HOY:
        meses.append(d.strftime("%Y-%m"))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return meses


def cargar(bd, usuario_caja=None):
    """Crea todo el polideportivo en la base de datos. 'bd' es una Sesion vacía."""
    tarifas = crear_tarifas()
    bd.agregar(*tarifas.values())
    bd.confirmar()

    # --- Grupos y socios --------------------------------------------------------
    grupos, socios = [], []
    for nombre, deporte, categoria, horario, entrenador, tarifa, plazas, (emin, emax), cuantos in GRUPOS:
        grupo = Equipo(nombre=nombre, deporte=deporte, categoria=categoria, horario=horario,
                       entrenador=entrenador, tarifa=tarifas[tarifa], plazas=plazas)
        grupos.append(grupo)
        for _ in range(cuantos):
            nacimiento = fecha_nacimiento(emin, emax)
            menor = (HOY.year - int(nacimiento[:4])) < 18
            mujer = azar.random() < (0.35 if deporte == "Fútbol" else 0.6)
            nombre_socio = nombre_al_azar(mujer)
            apellidos = nombre_socio.split(" ", 1)[1]
            pago = azar.choices(["Domiciliación", "Efectivo", "Transferencia"], [70, 20, 10])[0]
            usuario = sin_tildes(nombre_socio.split()[0].lower() + "." + nombre_socio.split()[1].lower())
            socio = Socio(
                nombre=nombre_socio,
                dni="" if (menor and azar.random() < 0.25) else dni_de_prueba(azar.randint(10_000_000, 79_999_999)),
                fecha_nacimiento=nacimiento,
                email=f"{usuario}{azar.randint(1, 99)}@correo.es",
                telefono=telefono(),
                direccion=f"{azar.choice(CALLES)}, {azar.randint(1, 120)}, {azar.choice(PUEBLOS)}",
                tutor=f"{nombre_al_azar(azar.random() < 0.6).split()[0]} {apellidos}" if menor else "",
                telefono_tutor=telefono() if menor else "",
                forma_pago=pago,
                iban=iban_al_azar() if pago == "Domiciliación" else "",
                fecha_alta=(date(2026, 9, 1) - timedelta(days=azar.choice([0, 0, 0, 365, 730, 1095, 1460]))
                            + timedelta(days=azar.randint(0, 20))).isoformat(),
                descuento=azar.choices([0, 10, 15], [85, 10, 5])[0],
                equipo=grupo,
            )
            if socio.descuento:
                socio.notas = "Descuento por hermanos" if menor else "Descuento por familia numerosa"
            socios.append(socio)

    # Algunos de baja (con su historial)
    for socio in azar.sample(socios, 6):
        socio.activo = False
        socio.notas = "Baja voluntaria"

    bd.agregar(*socios)
    bd.confirmar()

    # --- Cuotas de la temporada y su cobro --------------------------------------
    cuotas, movimientos = [], []
    meses = meses_de_temporada()
    for socio in socios:
        for i, mes in enumerate(meses):
            if not socio.activo and i == len(meses) - 1:
                continue  # el de baja ya no tiene cuota este mes
            importe = socio.importe_cuota()
            ultimo = i == len(meses) - 1
            pagada = azar.random() < (0.7 if ultimo else 0.95)
            dia = date(int(mes[:4]), int(mes[5:]), 5 if socio.forma_pago == "Domiciliación" else azar.randint(1, 12))
            if dia > HOY:
                pagada = False
            cuota = Cuota(socio=socio, mes=mes, importe=importe, pagada=pagada,
                          fecha_pago=dia.isoformat() if pagada else "")
            cuotas.append(cuota)
            if pagada:
                forma = socio.forma_pago if socio.forma_pago != "Efectivo" else azar.choice(["Efectivo", "Tarjeta"])
                movimientos.append(Movimiento(fecha=dia.isoformat(), hora=f"{azar.randint(9, 20)}:{azar.choice(['00', '15', '30', '45'])}",
                                              tipo="Cuota", concepto=f"Cuota {mes}", importe=importe, forma=forma,
                                              socio=socio, usuario=usuario_caja))
    bd.agregar(*cuotas)
    bd.confirmar()

    # --- Instalaciones y reservas (2 semanas atrás y 1 adelante) -----------------
    instalaciones = crear_instalaciones()
    bd.agregar(*instalaciones)
    bd.confirmar()
    adultos = [s for s in socios if s.activo and not s.es_menor]
    clientes_fuera = ["Peña Los Amigos", "Empresa Logística Turia", "Javier Ruiz", "Óscar Palau", "Grupo de pádel del barrio",
                      "Colegio San Roque", "Andrea Mas", "Rafa Navarro"]
    reservas = []
    for dias in range(-14, 8):
        dia = HOY + timedelta(days=dias)
        ocupado = set()
        for pista in instalaciones:
            # Más reservas por la tarde y el fin de semana, sobre todo en pádel
            probabilidad = {"Pádel": 0.45, "Tenis": 0.25, "Fútbol": 0.18, "Atletismo": 0.05}[pista.deporte]
            if dia.weekday() >= 5:
                probabilidad += 0.15
            for hora in range(HORA_APERTURA, HORA_CIERRE - 1):
                tarde = hora >= 17
                if (pista.id, hora) in ocupado or azar.random() > probabilidad * (1.6 if tarde else 0.5):
                    continue
                duracion = 2 if pista.deporte == "Fútbol" and azar.random() < 0.5 else 1
                if hora + duracion > HORA_CIERRE or (pista.id, hora + duracion - 1) in ocupado:
                    continue
                for h in range(hora, hora + duracion):
                    ocupado.add((pista.id, h))
                socio = azar.choice(adultos) if azar.random() < 0.7 else None
                reserva = Reserva(instalacion=pista, fecha=dia.isoformat(), hora_inicio=hora, duracion=duracion,
                                  socio=socio, nombre_cliente="" if socio else azar.choice(clientes_fuera),
                                  telefono="" if socio else telefono())
                reserva.importe = (pista.precio_socio if socio else pista.precio_no_socio) * duracion
                cancelada = dias < 0 and azar.random() < 0.05
                if cancelada:
                    reserva.estado = "Cancelada"
                elif dia < HOY or (dia == HOY and hora < 12) or azar.random() < 0.3:
                    reserva.pagada = True
                    movimientos.append(Movimiento(fecha=min(dia, HOY).isoformat(), hora=f"{max(hora - 1, 8)}:5{azar.randint(0, 9)}",
                                                  tipo="Reserva", concepto=f"{pista.nombre} {dia.isoformat()} {hora}:00-{hora + duracion}:00",
                                                  importe=reserva.importe, forma=azar.choice(["Tarjeta", "Tarjeta", "Efectivo"]),
                                                  socio=socio, usuario=usuario_caja))
                reservas.append(reserva)
    bd.mostrar_sql = False
    bd.agregar(*reservas)
    bd.confirmar()

    # --- Equipaciones -------------------------------------------------------------
    productos = crear_productos()
    bd.agregar(*productos)
    bd.confirmar()
    pedidos = []
    activos = [s for s in socios if s.activo]
    for _ in range(46):
        socio = azar.choice(activos)
        if socio.equipo.deporte == "Natación":
            producto = azar.choice([productos[5], productos[6], productos[7]])
        else:
            producto = azar.choice(productos[:5] + [productos[7]])
        if producto.stock < 1:
            continue
        edad = socio.edad or 30
        tallas = producto.lista_tallas
        if "Única" in tallas:
            talla = "Única"
        elif "Infantil" in tallas:
            talla = "Infantil" if edad < 14 else "Adulto"
        else:
            infantiles = [t for t in tallas if t.isdigit()]
            adultas = [t for t in tallas if not t.isdigit()]
            talla = (min(infantiles, key=lambda t: abs(int(t) - edad)) if edad < 15 and infantiles
                     else azar.choice(adultas[:4] or tallas))
        fecha = HOY - timedelta(days=azar.randint(0, 60))
        estado = azar.choices(["Entregado", "Pagado", "Pendiente de pago"], [65, 15, 20])[0]
        producto.stock -= 1
        pedido = Pedido(socio=socio, producto=producto, talla=talla, cantidad=1, importe=producto.precio,
                        fecha=fecha.isoformat(), estado=estado)
        pedidos.append(pedido)
        if estado != "Pendiente de pago":
            movimientos.append(Movimiento(fecha=fecha.isoformat(), hora=f"{azar.randint(10, 20)}:{azar.randint(10, 59)}",
                                          tipo="Equipación", concepto=f"{producto.nombre} talla {talla} x1",
                                          importe=producto.precio, forma=azar.choice(["Tarjeta", "Efectivo"]),
                                          socio=socio, usuario=usuario_caja))
    bd.agregar(*pedidos)
    bd.confirmar()

    # --- Caja: todos los cobros, ordenados por fecha y hora ---------------------------
    movimientos.sort(key=lambda m: (m.fecha, m.hora.zfill(5)))
    bd.agregar(*movimientos)
    bd.confirmar()

    return {"grupos": len(grupos), "socios": len(socios), "cuotas": len(cuotas), "reservas": len(reservas),
            "pedidos": len(pedidos), "movimientos": len(movimientos)}


def comprobar_categorias():
    """Para depurar: que la edad generada encaje con la categoría de cada grupo de fútbol."""
    errores = []
    for nombre, deporte, categoria, *_resto, (emin, emax), _n in GRUPOS:
        if deporte == "Fútbol":
            for edad in range(emin, emax + 1):
                if categoria_por_edad(edad) != categoria:
                    errores.append((nombre, edad, categoria_por_edad(edad)))
    return errores
