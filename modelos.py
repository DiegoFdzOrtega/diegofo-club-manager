"""
modelos.py — Mapeo objeto-relacional del club deportivo.

Cada clase es una TABLA, cada atributo es una COLUMNA y cada objeto es una FILA.

    Equipo 1 ──── * Socio 1 ──── * Cuota

Además de los campos del ORM, aquí se definen dos tipos de campo propios del
negocio (Dni e Iban): el ORM se puede ampliar heredando de sus campos.
"""

import hashlib
import hmac
import secrets
from datetime import date, datetime

from estadio_orm import Booleano, ClaveForanea, Entero, ErrorORM, Fecha, Modelo, Opcion, Relacion, Texto
from estadio_orm.campos import Texto as _Texto

FORMAS_PAGO = ["Domiciliación", "Efectivo", "Transferencia"]       # cómo paga el socio sus cuotas
FORMAS_COBRO = ["Efectivo", "Tarjeta", "Transferencia", "Domiciliación"]  # cómo se cobra en recepción
DEPORTES = ["Fútbol", "Natación", "Pádel", "Tenis", "Atletismo"]


# ---------------------------------------------------------------------------
# Campos propios del negocio
# ---------------------------------------------------------------------------

class Dni(_Texto):
    """DNI o NIE español con su letra comprobada. Puede quedar vacío."""
    LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"

    def validar(self, valor):
        valor = super().validar(valor).strip().upper().replace("-", "").replace(" ", "")
        if not valor:
            return valor
        numero = valor[:-1]
        if numero[:1] in "XYZ":                   # NIE: X=0, Y=1, Z=2
            numero = str("XYZ".index(numero[0])) + numero[1:]
        if len(valor) != 9 or not numero.isdigit() or not valor[-1].isalpha():
            raise ErrorORM(f"DNI/NIE con formato incorrecto: {valor}")
        if self.LETRAS[int(numero) % 23] != valor[-1]:
            raise ErrorORM(f"la letra del DNI/NIE {valor} no es correcta")
        return valor


class Iban(_Texto):
    """IBAN comprobado con su dígito de control (mod 97), como hacen los bancos. Puede quedar vacío."""

    def validar(self, valor):
        valor = super().validar(valor).replace(" ", "").upper()
        if not valor:
            return valor
        if len(valor) < 15 or not valor[:2].isalpha() or not valor[2:4].isdigit() or not valor.isalnum():
            raise ErrorORM(f"IBAN con formato incorrecto: {valor}")
        if valor.startswith("ES") and len(valor) != 24:
            raise ErrorORM("un IBAN español tiene 24 caracteres")
        # Se pasan los 4 primeros al final, las letras a números (A=10...) y el resto de /97 debe ser 1
        reordenado = valor[4:] + valor[:4]
        numero = "".join(str(int(c, 36)) for c in reordenado)
        if int(numero) % 97 != 1:
            raise ErrorORM(f"el IBAN {formatear_iban(valor)} no es válido (dígito de control incorrecto)")
        return valor


def formatear_iban(iban):
    """ES1234567890... -> ES12 3456 7890 ..."""
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def categoria_por_edad(edad):
    if edad is None:
        return None
    for limite, nombre in [(5, "Escuela"), (7, "Prebenjamín"), (9, "Benjamín"), (11, "Alevín"),
                           (13, "Infantil"), (15, "Cadete"), (18, "Juvenil")]:
        if edad <= limite:
            return nombre
    return "Senior"


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class Tarifa(Modelo):
    """Cuota mensual: Base 30 €, Competición 50 €, Premium 100 €... La edita la secretaría."""
    __tabla__ = "tarifas"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=30)
    importe = Entero()                         # euros al mes
    descripcion = Texto()
    activa = Booleano(por_defecto=True)

    def antes_de_guardar(self):
        if self.importe <= 0:
            raise ErrorORM("el importe de la tarifa debe ser mayor que 0")

    def __str__(self):
        return f"{self.nombre} ({self.importe} €/mes)"


class Equipo(Modelo):
    """Un equipo (Alevín A, Senior...) o un grupo de una actividad (Natación Iniciación, Aquagym...)."""
    __tabla__ = "equipos"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=40)
    categoria = Texto(obligatorio=True)        # Prebenjamín, Alevín, Infantil, Senior... o nivel
    entrenador = Texto()
    tarifa = ClaveForanea(Tarifa)              # tarifa por defecto de sus miembros
    deporte = Opcion(DEPORTES, por_defecto="Fútbol")
    horario = Texto()                          # "L-X 17:30-19:00"
    plazas = Entero()                          # 0 = sin límite

    socios = Relacion("Socio", "equipo")       # equipo.socios -> lista de Socio (no es columna)

    def ocupadas(self):
        if self._sesion is None or self.id is None:
            return 0
        return self._sesion.consulta(Socio).filtrar(equipo=self, activo=True).contar()

    def __str__(self):
        return f"{self.nombre} ({self.categoria})"


class Socio(Modelo):
    __tabla__ = "socios"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=60)
    dni = Dni()
    fecha_nacimiento = Fecha()
    email = Texto()
    telefono = Texto()
    direccion = Texto()
    tutor = Texto()                            # obligatorio en la práctica para menores
    telefono_tutor = Texto()
    forma_pago = Opcion(FORMAS_PAGO, por_defecto="Efectivo")
    iban = Iban()
    fecha_alta = Fecha()
    activo = Booleano(por_defecto=True)
    notas = Texto()
    equipo = ClaveForanea(Equipo, obligatorio=True)   # columna equipo_id
    tarifa = ClaveForanea(Tarifa)              # si está vacía, se usa la de su equipo
    descuento = Entero()                       # % de descuento (hermanos, familia numerosa...)

    cuotas = Relacion("Cuota", "socio")
    pedidos = Relacion("Pedido", "socio")
    reservas = Relacion("Reserva", "socio")

    # --- Cuota que le toca pagar ------------------------------------------------
    @property
    def tarifa_aplicada(self):
        return self.tarifa or (self.equipo.tarifa if self.equipo else None)

    def importe_cuota(self):
        base = self.tarifa_aplicada.importe if self.tarifa_aplicada else 30
        return round(base * (100 - (self.descuento or 0)) / 100)

    # --- Datos calculados (no se guardan: se calculan al leerlos) -------------
    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None
        nacimiento = date.fromisoformat(self.fecha_nacimiento)
        hoy = date.today()
        return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))

    @property
    def es_menor(self):
        return self.edad is not None and self.edad < 18

    @property
    def categoria_edad(self):
        return categoria_por_edad(self.edad)

    @property
    def iban_oculto(self):
        """Para listados: ES12 **** **** **** **** 1234 (protección de datos)."""
        if not self.iban:
            return ""
        return f"{self.iban[:4]} **** **** **** **** {self.iban[-4:]}"

    def avisos(self, con_pagos=True):
        """Lo que le falta a la ficha para estar completa (con_pagos=False: sin hablar de datos bancarios)."""
        lista = []
        if self.es_menor and not self.tutor:
            lista.append("Es menor de edad y no tiene tutor registrado.")
        if con_pagos and self.forma_pago == "Domiciliación" and not self.iban:
            lista.append("Paga por domiciliación pero no tiene IBAN.")
        if not self.dni:
            lista.append("Falta el DNI/NIE.")
        if (self.categoria_edad and self._sesion is not None and self.equipo.deporte == "Fútbol"
                and self.equipo.categoria != self.categoria_edad):
            lista.append(f"Por edad le corresponde la categoría {self.categoria_edad} "
                         f"y está en un equipo {self.equipo.categoria}.")
        return lista

    def antes_de_guardar(self):
        """El ORM llama a este método antes de cada INSERT/UPDATE: reglas que dependen de varios campos."""
        if not 0 <= (self.descuento or 0) <= 100:
            raise ErrorORM("el descuento debe estar entre 0 y 100 %")
        if self.forma_pago == "Domiciliación" and not self.iban:
            raise ErrorORM("para pagar por domiciliación hace falta el IBAN")
        if self.es_menor and not self.tutor.strip():
            raise ErrorORM("un socio menor de edad necesita un tutor")
        # Plazas del grupo: solo se comprueba al entrar en él (alta o cambio de grupo)
        grupo = self.equipo
        if (self.activo and grupo is not None and grupo.plazas and self._sesion is not None
                and grupo.id is not None
                and ("equipo_id" in self._cambios or "activo" in self._cambios or self.id is None)):
            otros = self._sesion.consulta(Socio).filtrar(equipo=grupo, activo=True).todos()
            if len([o for o in otros if o.id != self.id]) >= grupo.plazas:
                raise ErrorORM(f"el grupo {grupo.nombre} está completo ({grupo.plazas} plazas)")

    def __str__(self):
        return self.nombre


class Cuota(Modelo):
    __tabla__ = "cuotas"

    id = Entero(primaria=True)
    socio = ClaveForanea(Socio, obligatorio=True)     # columna socio_id
    mes = Texto(obligatorio=True)              # AAAA-MM
    importe = Entero()                         # en euros
    pagada = Booleano(por_defecto=False)
    fecha_pago = Fecha()


# ---------------------------------------------------------------------------
# Reservas de pistas
# ---------------------------------------------------------------------------

HORA_APERTURA = 8    # la primera reserva puede empezar a las 8:00
HORA_CIERRE = 23     # la última tiene que acabar como muy tarde a las 23:00


class Instalacion(Modelo):
    __tabla__ = "instalaciones"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=40)
    deporte = Opcion(DEPORTES)
    precio_socio = Entero()          # €/hora
    precio_no_socio = Entero()       # €/hora
    activa = Booleano(por_defecto=True)

    def __str__(self):
        return self.nombre


class Reserva(Modelo):
    __tabla__ = "reservas"

    id = Entero(primaria=True)
    instalacion = ClaveForanea(Instalacion, obligatorio=True)
    fecha = Fecha(obligatorio=True)
    hora_inicio = Entero()           # 8 = 8:00
    duracion = Entero(por_defecto=1) # horas
    socio = ClaveForanea(Socio)      # vacío si reserva alguien que no es socio
    nombre_cliente = Texto()
    telefono = Texto()
    importe = Entero()
    pagada = Booleano(por_defecto=False)
    estado = Opcion(["Confirmada", "Cancelada"])
    creada_por = ClaveForanea("Usuario")

    @property
    def hora_fin(self):
        return self.hora_inicio + self.duracion

    @property
    def cliente(self):
        return self.socio.nombre if self.socio else self.nombre_cliente

    def calcular_importe(self):
        precio = self.instalacion.precio_socio if self.socio_id else self.instalacion.precio_no_socio
        return precio * self.duracion

    def antes_de_guardar(self):
        """Reglas de la reserva: horario, cliente y, sobre todo, que la pista no esté ya ocupada."""
        if self.estado == "Cancelada":
            return  # una reserva cancelada no ocupa la pista
        if not 1 <= self.duracion <= 3:
            raise ErrorORM("una reserva dura entre 1 y 3 horas")
        if self.hora_inicio < HORA_APERTURA or self.hora_fin > HORA_CIERRE:
            raise ErrorORM(f"las pistas abren de {HORA_APERTURA}:00 a {HORA_CIERRE}:00")
        if not self.socio_id and not self.nombre_cliente.strip():
            raise ErrorORM("indica el socio o el nombre de quien reserva")
        otras = (self._sesion.consulta(Reserva)
                 .filtrar(instalacion_id=self.instalacion_id, fecha=self.fecha, estado="Confirmada").todos())
        for otra in otras:
            if otra.id != self.id and self.hora_inicio < otra.hora_fin and otra.hora_inicio < self.hora_fin:
                raise ErrorORM(f"{self.instalacion.nombre} ya está reservada de {otra.hora_inicio}:00 "
                               f"a {otra.hora_fin}:00 ({otra.cliente})")


# ---------------------------------------------------------------------------
# Equipaciones (tienda del club)
# ---------------------------------------------------------------------------

class Producto(Modelo):
    __tabla__ = "productos"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=50)
    precio = Entero()                # €
    tallas = Texto()                 # "8,10,12,S,M,L,XL"
    stock = Entero()                 # unidades en el almacén
    activo = Booleano(por_defecto=True)

    @property
    def lista_tallas(self):
        return [t.strip() for t in self.tallas.split(",") if t.strip()]

    def antes_de_guardar(self):
        if self.stock < 0:
            raise ErrorORM(f"no hay stock suficiente de {self.nombre}")
        if self.precio < 0:
            raise ErrorORM("el precio no puede ser negativo")

    def __str__(self):
        return self.nombre


class Pedido(Modelo):
    __tabla__ = "pedidos"

    id = Entero(primaria=True)
    socio = ClaveForanea(Socio, obligatorio=True)
    producto = ClaveForanea(Producto, obligatorio=True)
    talla = Texto()
    cantidad = Entero(por_defecto=1)
    importe = Entero()
    fecha = Fecha()
    estado = Opcion(["Pendiente de pago", "Pagado", "Entregado", "Cancelado"])

    def antes_de_guardar(self):
        if self.cantidad < 1:
            raise ErrorORM("la cantidad debe ser al menos 1")
        if self.talla and self.talla not in self.producto.lista_tallas:
            raise ErrorORM(f"{self.producto.nombre} no tiene la talla {self.talla}")


# ---------------------------------------------------------------------------
# Usuarios de la aplicación (los trabajadores del club)
# ---------------------------------------------------------------------------

ROLES = ["Administrador", "Secretaría", "Entrenador"]

# Qué puede hacer cada rol
PERMISOS = {
    "Administrador": {"ver_todos", "editar_socios", "cuotas", "informe", "datos_bancarios", "usuarios", "ver_sql",
                      "tarifas", "reservas", "ver_reservas", "tienda", "caja"},
    "Secretaría": {"ver_todos", "editar_socios", "cuotas", "informe", "datos_bancarios",
                   "tarifas", "reservas", "ver_reservas", "tienda", "caja"},
    "Entrenador": {"ver_reservas"},  # sus jugadores (sin datos bancarios) y el calendario de pistas
}

ITERACIONES = 200_000  # cuantas más, más le cuesta a un atacante probar contraseñas


class Usuario(Modelo):
    __tabla__ = "usuarios"

    id = Entero(primaria=True)
    nombre = Texto(obligatorio=True, largo_maximo=60)
    usuario = Texto(obligatorio=True, largo_maximo=30)   # con el que inicia sesión
    clave = Texto()                                      # NUNCA la contraseña: su "huella" (hash)
    rol = Opcion(ROLES, por_defecto="Secretaría")
    equipo = ClaveForanea(Equipo)                        # solo para entrenadores (0 = ninguno)
    activo = Booleano(por_defecto=True)
    ultimo_acceso = Texto()

    # --- Contraseñas ----------------------------------------------------------
    # Se guarda un hash PBKDF2 con "sal" aleatoria: aunque alguien robe la base
    # de datos, no puede leer las contraseñas ni saber si dos usuarios usan la misma.
    def poner_clave(self, clave):
        if len(clave) < 6:
            raise ErrorORM("la contraseña debe tener al menos 6 caracteres")
        sal = secrets.token_hex(16)
        huella = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), ITERACIONES).hex()
        self.clave = f"pbkdf2${ITERACIONES}${sal}${huella}"

    def comprobar_clave(self, clave):
        try:
            _, iteraciones, sal, huella = self.clave.split("$")
        except ValueError:
            return False
        calculada = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal), int(iteraciones)).hex()
        return hmac.compare_digest(calculada, huella)  # comparación que no da pistas por el tiempo

    # --- Permisos ---------------------------------------------------------------
    def puede(self, permiso):
        return permiso in PERMISOS.get(self.rol, set())

    def puede_ver_socio(self, socio):
        return self.puede("ver_todos") or (self.equipo_id is not None and socio.equipo_id == self.equipo_id)

    def antes_de_guardar(self):
        self.__dict__["usuario"] = self.usuario.strip().lower()
        if " " in self.usuario:
            raise ErrorORM("el nombre de usuario no puede tener espacios")
        if not self.clave:
            raise ErrorORM("el usuario necesita una contraseña")
        if self.rol == "Entrenador" and self.equipo_id is None and not self._referencias:
            raise ErrorORM("un entrenador debe tener un equipo asignado")

    def __str__(self):
        return f"{self.nombre} ({self.rol})"


# ---------------------------------------------------------------------------
# Caja: todo lo que se cobra en recepción
# ---------------------------------------------------------------------------

class Movimiento(Modelo):
    __tabla__ = "movimientos"

    id = Entero(primaria=True)
    fecha = Fecha(obligatorio=True)
    hora = Texto()
    tipo = Opcion(["Cuota", "Reserva", "Equipación", "Otro"])
    concepto = Texto(obligatorio=True)
    importe = Entero()
    forma = Opcion(FORMAS_COBRO)
    socio = ClaveForanea(Socio)          # vacío si no es socio (p. ej. una reserva de fuera)
    usuario = ClaveForanea(Usuario)      # quién lo cobró

    @staticmethod
    def nuevo(tipo, concepto, importe, forma, usuario, socio=None):
        ahora = datetime.now()
        return Movimiento(fecha=ahora.date().isoformat(), hora=ahora.strftime("%H:%M"), tipo=tipo,
                          concepto=concepto, importe=importe, forma=forma, usuario=usuario, socio=socio)


# Orden en el que se crean las tablas (las referenciadas, antes)
TODOS = (Tarifa, Equipo, Socio, Cuota, Usuario, Instalacion, Reserva, Producto, Pedido, Movimiento)
