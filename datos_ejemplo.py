"""
datos_ejemplo.py — Datos INVENTADOS para la demo del club.

Los DNI e IBAN no son de nadie: se calculan aquí para que tengan la letra y los
dígitos de control correctos y así pasen la validación.
"""

from datetime import date, timedelta

from modelos import Cuota, Dni, Equipo, Instalacion, Pedido, Producto, Reserva, Socio, Tarifa


def dni_de_prueba(numero):
    """12345678 -> 12345678Z (con la letra correcta)."""
    return f"{numero:08d}{Dni.LETRAS[numero % 23]}"


def iban_de_prueba(cuenta):
    """20 dígitos de cuenta -> IBAN español con los dígitos de control correctos."""
    numero = int("".join(str(int(c, 36)) for c in cuenta + "ES00"))
    control = 98 - numero % 97
    return f"ES{control:02d}{cuenta}"


def crear_tarifas():
    return [
        Tarifa(nombre="Base", importe=30, descripcion="Escuela y categorías inferiores"),
        Tarifa(nombre="Competición", importe=50, descripcion="Equipos federados"),
        Tarifa(nombre="Premium", importe=100, descripcion="Senior con fisioterapia y gimnasio"),
    ]


def crear_equipos(tarifas=None):
    base, competicion, premium = tarifas or crear_tarifas()
    return [
        Equipo(nombre="Alevín A", categoria="Alevín", entrenador="Rosa Gil", tarifa=base),
        Equipo(nombre="Infantil B", categoria="Infantil", entrenador="Toni Vidal", tarifa=competicion),
        Equipo(nombre="Senior", categoria="Senior", entrenador="Paco Ferrer", tarifa=premium),
    ]


def crear_instalaciones():
    return [
        Instalacion(nombre="Campo de fútbol 7", deporte="Fútbol", precio_socio=30, precio_no_socio=50),
        Instalacion(nombre="Pista de tenis", deporte="Tenis", precio_socio=8, precio_no_socio=14),
        Instalacion(nombre="Pádel 1", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pádel 2", deporte="Pádel", precio_socio=10, precio_no_socio=16),
        Instalacion(nombre="Pista de atletismo", deporte="Atletismo", precio_socio=3, precio_no_socio=6),
    ]


def crear_productos():
    return [
        Producto(nombre="Camiseta oficial", precio=35, tallas="8,10,12,14,S,M,L,XL", stock=40),
        Producto(nombre="Pantalón oficial", precio=20, tallas="8,10,12,14,S,M,L,XL", stock=40),
        Producto(nombre="Medias", precio=8, tallas="Única", stock=60),
        Producto(nombre="Chándal de paseo", precio=55, tallas="8,10,12,14,S,M,L,XL", stock=15),
        Producto(nombre="Mochila del club", precio=25, tallas="Única", stock=3),
    ]


def crear_reservas_y_pedidos(socios, instalaciones, productos):
    """Algunas reservas para hoy y mañana, y un par de pedidos, para que la demo no esté vacía."""
    hoy = date.today()
    manana = (hoy + timedelta(days=1)).isoformat()
    hoy = hoy.isoformat()
    futbol, tenis, padel1, padel2, atletismo = instalaciones
    camiseta, pantalon, medias, chandal, mochila = productos
    reservas = [
        Reserva(instalacion=padel1, fecha=hoy, hora_inicio=18, duracion=1, socio=socios[-2]),
        Reserva(instalacion=padel2, fecha=hoy, hora_inicio=19, duracion=2, nombre_cliente="Javier Ruiz",
                telefono="622 111 222"),
        Reserva(instalacion=tenis, fecha=hoy, hora_inicio=10, duracion=1, socio=socios[-1]),
        Reserva(instalacion=futbol, fecha=hoy, hora_inicio=20, duracion=2, nombre_cliente="Peña Los Amigos",
                telefono="633 444 555"),
        Reserva(instalacion=padel1, fecha=manana, hora_inicio=9, duracion=1, socio=socios[0]),
    ]
    for r in reservas:
        r.importe = (r.instalacion.precio_socio if r.socio else r.instalacion.precio_no_socio) * r.duracion
    pedidos = [
        Pedido(socio=socios[0], producto=camiseta, talla="12", cantidad=1, importe=35, fecha=hoy),
        Pedido(socio=socios[1], producto=chandal, talla="14", cantidad=1, importe=55, fecha=hoy, estado="Pagado"),
    ]
    camiseta.stock -= 1
    chandal.stock -= 1
    return reservas, pedidos


def crear_socios(alevin, infantil, senior):
    """Devuelve una lista de socios inventados con su ficha completa."""
    datos = [
        # nombre, nacimiento, equipo, tutor, pago
        ("Lucía Martí", "2015-03-12", alevin, "Elena Ros", "Domiciliación"),
        ("Mario Sanz", "2015-07-30", alevin, "Jorge Sanz", "Efectivo"),
        ("Nora Peris", "2013-11-02", infantil, "Marta Peris", "Domiciliación"),
        ("Iker Soler", "2013-05-21", infantil, "Pau Soler", "Transferencia"),
        ("Adrián Gómez", "1996-01-08", senior, "", "Domiciliación"),
        ("Carla Ibáñez", "1999-09-17", senior, "", "Domiciliación"),
    ]
    socios = []
    for i, (nombre, nacimiento, equipo, tutor, pago) in enumerate(datos, start=1):
        usuario = nombre.split()[0].lower().replace("í", "i").replace("á", "a")
        socios.append(Socio(
            nombre=nombre,
            dni=dni_de_prueba(10000000 + i * 1234567),
            fecha_nacimiento=nacimiento,
            email=f"{usuario}@correo.es",
            telefono=f"600 00{i} 00{i}",
            direccion=f"C/ Ejemplo, {i * 3}, Valencia",
            tutor=tutor,
            telefono_tutor=f"611 00{i} 00{i}" if tutor else "",
            forma_pago=pago,
            iban=iban_de_prueba(f"{2100 + i:04d}{i * 111:04d}00{i * 7654321:010d}") if pago == "Domiciliación" else "",
            fecha_alta=f"202{3 + i % 3}-09-0{i}",
            equipo=equipo,
        ))
    socios[3].descuento = 10
    socios[3].notas = "Descuento del 10 % por familia numerosa"
    return socios


def cuotas_de(socio, meses_pagados=("2026-10",), meses_pendientes=("2026-11",)):
    importe = socio.importe_cuota()
    cuotas = [Cuota(socio=socio, mes=m, importe=importe, pagada=True, fecha_pago=f"{m}-05") for m in meses_pagados]
    cuotas += [Cuota(socio=socio, mes=m, importe=importe) for m in meses_pendientes]
    return cuotas
