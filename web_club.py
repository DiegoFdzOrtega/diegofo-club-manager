"""
web_club.py — estadio · Club Manager: aplicación web para los TRABAJADORES del club.

Hecha con Flask + estadio_orm (que funciona sobre la base de datos estadio, en C++).

Antes de ejecutar:   pip install flask
Ejecutar:            python web_club.py
Abrir:               http://localhost:5000

Roles:
  - Administrador: todo, incluida la gestión de usuarios y el panel de SQL.
  - Secretaría:    socios, cuotas, cobros, remesa bancaria e informes.
  - Entrenador:    solo los jugadores de su equipo, sin datos bancarios.
"""

import configparser
import csv
import io
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for

import sys

import datos_polideportivo
from datos_ejemplo import crear_instalaciones, crear_productos, crear_tarifas
from estadio_orm import ErrorORM, Sesion
from modelos import (DEPORTES, FORMAS_COBRO, FORMAS_PAGO, HORA_APERTURA, HORA_CIERRE, ROLES, TODOS, Cuota, Equipo,
                     Instalacion, Movimiento, Pedido, Producto, Reserva, Socio, Tarifa, Usuario, formatear_iban)

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(CARPETA, "estadio.ini")

_ini = configparser.ConfigParser(inline_comment_prefixes=(";",))
_ini.read(CONFIG, encoding="utf-8")
NOMBRE_CLUB = _ini.get("club", "nombre", fallback="Mi club")

app = Flask(__name__, template_folder="plantillas", static_folder="estaticos")


def clave_secreta():
    """Clave para firmar las cookies de sesión. Se crea una vez y se guarda en un fichero (fuera de Git)."""
    fichero = os.path.join(CARPETA, ".clave_web")
    if not os.path.exists(fichero):
        with open(fichero, "w") as f:
            f.write(secrets.token_hex(32))
    with open(fichero) as f:
        return f.read().strip()


app.secret_key = clave_secreta()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# Campos de la ficha que se pueden editar desde el formulario
CAMPOS_FICHA = ["nombre", "dni", "fecha_nacimiento", "email", "telefono", "direccion",
                "tutor", "telefono_tutor", "forma_pago", "iban", "notas"]


# ---------------------------------------------------------------------------
# Una sesión del ORM por petición + quién ha iniciado sesión
# ---------------------------------------------------------------------------

@app.before_request
def antes_de_cada_peticion():
    g.bd = Sesion(ruta_config=CONFIG)
    g.bd.mostrar_sql = False
    g.usuario = None
    if "usuario_id" in session:
        usuario = g.bd.obtener(Usuario, session["usuario_id"])
        if usuario and usuario.activo:
            g.usuario = usuario
        else:
            session.clear()
    if g.usuario is None and request.endpoint not in ("entrar", "static"):
        return redirect(url_for("entrar", siguiente=request.path))


@app.teardown_request
def despues_de_cada_peticion(error):
    bd = g.pop("bd", None)
    if bd is not None:
        bd.cerrar()


def requiere(permiso):
    """Decorador: la página solo la pueden abrir los roles con ese permiso."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not g.usuario.puede(permiso):
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


@app.errorhandler(403)
def prohibido(error):
    flash("No tienes permiso para entrar ahí.", "error")
    return redirect(url_for("inicio"))


def volver(destino, **args):
    """Después de una acción (POST), guarda su SQL y redirige (patrón POST-Redirect-GET)."""
    session["sql_accion"] = g.bd.registro[-40:]
    return redirect(url_for(destino, **args))


def socio_visible(id_):
    """El socio, si existe y el usuario puede verlo. Si no, None (y un aviso)."""
    socio = g.bd.obtener(Socio, id_)
    if socio is None:
        flash(f"No existe el socio nº {id_}.", "error")
        return None
    if not g.usuario.puede_ver_socio(socio):
        flash("Ese socio no es de tu equipo.", "error")
        return None
    return socio


def rellenar_ficha(socio, formulario):
    """Copia el formulario al objeto. El ORM valida cada campo al asignarlo."""
    for campo in CAMPOS_FICHA:
        setattr(socio, campo, formulario.get(campo, "").strip())
    socio.equipo = g.bd.obtener(Equipo, int(formulario["equipo"]))
    id_tarifa = int(formulario.get("tarifa", 0) or 0)
    socio.tarifa = g.bd.obtener(Tarifa, id_tarifa) if id_tarifa else None
    socio.descuento = int(formulario.get("descuento", 0) or 0)


def cobrar(tipo, concepto, importe, socio=None):
    """Apunta un cobro en la caja (dentro de la transacción en curso) y deja preparado su recibo."""
    forma = request.form.get("forma", "Efectivo")
    movimiento = Movimiento.nuevo(tipo, concepto, importe, forma, g.usuario, socio)
    g.bd.agregar(movimiento)
    return movimiento


def ocupacion_grupos():
    """{id del grupo: socios de alta en él}"""
    cuenta = {}
    for fila in g.bd.sql("SELECT equipo_id, COUNT(*) AS n FROM socios WHERE activo = ? GROUP BY equipo_id", (1,)):
        cuenta[fila["equipo_id"]] = fila["n"]
    return cuenta


def motivo(error):
    """Texto del error para el usuario, sin el prefijo técnico del ORM."""
    return str(error).replace("no se ha guardado nada: ", "")


def recibo_listo(movimiento):
    session["recibo"] = movimiento.id


# ---------------------------------------------------------------------------
# Iniciar y cerrar sesión, mi cuenta
# ---------------------------------------------------------------------------

@app.route("/entrar", methods=["GET", "POST"])
def entrar():
    if request.method == "POST":
        nombre = request.form.get("usuario", "").strip().lower()
        clave = request.form.get("clave", "")
        usuario = g.bd.consulta(Usuario).filtrar(usuario=nombre).primero()
        # Mismo mensaje si no existe o si la contraseña está mal: así no se da pistas
        if usuario is None or not usuario.activo or not usuario.comprobar_clave(clave):
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("entrar.html", usuario=nombre)
        usuario.ultimo_acceso = datetime.now().strftime("%Y-%m-%d %H:%M")
        g.bd.confirmar()
        session.clear()
        session["usuario_id"] = usuario.id
        flash(f"Hola, {usuario.nombre}.", "ok")
        siguiente = request.args.get("siguiente", "")
        return redirect(siguiente if siguiente.startswith("/") and not siguiente.startswith("//") else url_for("inicio"))
    return render_template("entrar.html", usuario="")


@app.route("/salir")
def salir():
    session.clear()
    flash("Has cerrado la sesión.", "ok")
    return redirect(url_for("entrar"))


@app.route("/mi-cuenta", methods=["GET", "POST"])
def mi_cuenta():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        if not g.usuario.comprobar_clave(actual):
            flash("La contraseña actual no es correcta.", "error")
        elif nueva != request.form.get("repetir", ""):
            flash("Las dos contraseñas nuevas no coinciden.", "error")
        else:
            try:
                g.usuario.poner_clave(nueva)
                g.bd.confirmar()
                flash("Contraseña cambiada.", "ok")
                return volver("inicio")
            except ErrorORM as e:
                g.bd.deshacer()
                flash(motivo(e), "error")
    return render_template("mi_cuenta.html")


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------

@app.route("/")
def inicio():
    if g.usuario.puede("ver_todos"):
        equipos = g.bd.consulta(Equipo).ordenar("id").todos()
    else:
        equipos = [g.usuario.equipo] if g.usuario.equipo else []
    if g.usuario.puede("ver_todos"):
        g.bd.consulta(Tarifa).todos()
        activos = g.bd.consulta(Socio).filtrar(activo=True).todos()
        por_grupo = {}
        for socio in activos:
            por_grupo.setdefault(socio.equipo_id, []).append(socio)
        plantillas = []  # al personal de oficina se le enseñan las secciones, no todas las plantillas
        jugadores = activos
        secciones = {}
        for e in equipos:
            sec = secciones.setdefault(e.deporte or "Otros", {"grupos": 0, "socios": 0, "plazas": 0, "llenos": 0})
            n = len(por_grupo.get(e.id, []))
            sec["grupos"] += 1
            sec["socios"] += n
            sec["plazas"] += e.plazas
            sec["llenos"] += 1 if e.plazas and n >= e.plazas else 0
    else:
        plantillas = [(e, [s for s in e.socios if s.activo]) for e in equipos]
        jugadores = [s for _, lista in plantillas for s in lista]
        secciones = {}

    resumen = None
    if g.usuario.puede("cuotas"):
        resumen = {
            "equipos": len(equipos),
            "socios": len(jugadores),
            "pendientes": g.bd.consulta(Cuota).filtrar(pagada=False).contar(),
            "deuda": g.bd.sql("SELECT SUM(importe) AS total FROM cuotas WHERE pagada = ?", (0,))[0]["total"],
        }
    hoy = None
    if g.usuario.puede("caja"):
        g.bd.consulta(Instalacion).todos()
        hoy = {
            "reservas": g.bd.consulta(Reserva).filtrar(fecha=date.today().isoformat(), estado="Confirmada")
                        .ordenar("hora_inicio").todos(),
            "hora": datetime.now().hour,
            "cobrado": g.bd.sql("SELECT SUM(importe) AS total FROM movimientos WHERE fecha = ?",
                                (date.today().isoformat(),))[0]["total"],
            "por_entregar": g.bd.consulta(Pedido).filtrar(estado="Pagado").contar(),
            "por_cobrar": g.bd.consulta(Pedido).filtrar(estado="Pendiente de pago").contar(),
        }
    con_pagos = g.usuario.puede("datos_bancarios")
    incompletas = [(s, s.avisos(con_pagos)) for s in jugadores if s.avisos(con_pagos)]
    return render_template("inicio.html", resumen=resumen, plantillas=plantillas, incompletas=incompletas, hoy=hoy,
                           secciones=secciones)


# ---------------------------------------------------------------------------
# Socios
# ---------------------------------------------------------------------------

@app.route("/socios")
def socios():
    texto = request.args.get("q", "").strip()
    ver = request.args.get("ver", "activos")
    grupo = int(request.args.get("grupo", 0) or 0)
    deporte = request.args.get("deporte", "")
    equipos = g.bd.consulta(Equipo).ordenar("id").todos()  # quedan en el mapa de identidad
    consulta = g.bd.consulta(Socio).ordenar("nombre")
    if grupo:
        consulta = consulta.filtrar(equipo_id=grupo)
    if not g.usuario.puede("ver_todos"):
        consulta = consulta.filtrar(equipo_id=g.usuario.equipo_id)  # el entrenador, solo su equipo
    if texto:
        consulta = consulta.buscar("nombre", texto)
    if ver in ("activos", "bajas", "revisar"):
        consulta = consulta.filtrar(activo=(ver != "bajas"))
    lista = consulta.todos()
    if deporte:
        lista = [s for s in lista if s.equipo.deporte == deporte]
    if ver == "revisar":
        con_pagos = g.usuario.puede("datos_bancarios")
        lista = [s for s in lista if s.avisos(con_pagos)]
    return render_template("socios.html", socios=lista, q=texto, ver=ver, grupo=grupo, deporte=deporte,
                           equipos=equipos, deportes=DEPORTES)


@app.route("/socios/nuevo", methods=["GET", "POST"])
@requiere("editar_socios")
def socio_nuevo():
    equipos = g.bd.consulta(Equipo).ordenar("id").todos()
    if request.method == "POST":
        try:
            socio = Socio(nombre=request.form.get("nombre", "").strip(), fecha_alta=date.today().isoformat(),
                          equipo=equipos[0])
            rellenar_ficha(socio, request.form)
            with g.bd.transaccion():  # alta + primera cuota: las dos o ninguna
                g.bd.agregar(socio)
                g.bd.agregar(Cuota(socio=socio, mes=date.today().strftime("%Y-%m"), importe=socio.importe_cuota()))
            flash(f"Alta de {socio.nombre} como socio nº {socio.id}, con su primera cuota.", "ok")
            return volver("ficha", id_=socio.id)
        except (ErrorORM, ValueError, KeyError) as e:
            flash(f"No se pudo dar de alta: {motivo(e)}", "error")
    return render_template("formulario.html", socio=None, valores=request.form, equipos=equipos,
                           formas_pago=FORMAS_PAGO, tarifas=g.bd.consulta(Tarifa).filtrar(activa=True).todos(),
                           ocupacion=ocupacion_grupos())


@app.route("/socios/<int:id_>")
def ficha(id_):
    socio = socio_visible(id_)
    if socio is None:
        return volver("socios")
    cuotas, totales, pedidos, reservas = [], {}, [], []
    if g.usuario.puede("datos_bancarios"):
        cuotas = g.bd.consulta(Cuota).filtrar(socio=socio).ordenar("-mes").todos()
        g.bd.consulta(Producto).todos()
        pedidos = g.bd.consulta(Pedido).filtrar(socio=socio).ordenar("-id").todos()
        reservas = g.bd.consulta(Reserva).filtrar(socio=socio).ordenar("-fecha").limite(10).todos()
        totales = {
            "pagado": sum(c.importe for c in cuotas if c.pagada),
            "pendiente": sum(c.importe for c in cuotas if not c.pagada),
        }
    antiguedad = None
    if socio.fecha_alta:
        antiguedad = (date.today() - date.fromisoformat(socio.fecha_alta)).days // 365
    return render_template("ficha.html", s=socio, cuotas=cuotas, totales=totales, antiguedad=antiguedad,
                           iban_completo=formatear_iban(socio.iban), pedidos=pedidos, reservas=reservas)


@app.route("/socios/<int:id_>/editar", methods=["GET", "POST"])
@requiere("editar_socios")
def editar(id_):
    socio = socio_visible(id_)
    if socio is None:
        return volver("socios")
    equipos = g.bd.consulta(Equipo).ordenar("id").todos()
    if request.method == "POST":
        try:
            rellenar_ficha(socio, request.form)
            g.bd.confirmar()  # solo hace UPDATE de lo que ha cambiado
            flash("Ficha guardada.", "ok")
            return volver("ficha", id_=id_)
        except (ErrorORM, ValueError, KeyError) as e:
            g.bd.deshacer()
            flash(f"No se ha guardado: {motivo(e)}", "error")
    return render_template("formulario.html", socio=socio, valores=request.form, equipos=equipos,
                           formas_pago=FORMAS_PAGO, tarifas=g.bd.consulta(Tarifa).filtrar(activa=True).todos(),
                           ocupacion=ocupacion_grupos())


@app.post("/socios/<int:id_>/activo")
@requiere("editar_socios")
def cambiar_activo(id_):
    socio = socio_visible(id_)
    if socio:
        socio.activo = not socio.activo
        g.bd.confirmar()
        flash(f"{socio.nombre} {'vuelve a estar de alta' if socio.activo else 'queda de baja (se conserva su historial)'}.", "ok")
        return volver("ficha", id_=id_)
    return volver("socios")


@app.post("/socios/<int:id_>/eliminar")
@requiere("editar_socios")
def eliminar(id_):
    socio = socio_visible(id_)
    if socio:
        try:
            with g.bd.transaccion():  # sus cuotas y él, todo junto
                for cuota in socio.cuotas:
                    g.bd.borrar(cuota)
                g.bd.borrar(socio)
            flash(f"{socio.nombre} y todo su historial se han eliminado.", "ok")
        except ErrorORM as e:
            flash(f"No se pudo eliminar: {motivo(e)}", "error")
    return volver("socios")


# ---------------------------------------------------------------------------
# Cuotas
# ---------------------------------------------------------------------------

@app.route("/cuotas")
@requiere("cuotas")
def cuotas():
    solo_pendientes = request.args.get("ver", "pendientes") == "pendientes"
    g.bd.consulta(Socio).todos()  # cargar socios de una vez (luego cuota.socio no hace más consultas)
    consulta = g.bd.consulta(Cuota).ordenar("mes")
    if solo_pendientes:
        consulta = consulta.filtrar(pagada=False)
    return render_template("cuotas.html", cuotas=consulta.todos(), solo_pendientes=solo_pendientes,
                           mes_actual=date.today().strftime("%Y-%m"))


@app.post("/cuotas/<int:id_>/cobrar")
@requiere("cuotas")
def cuota_cobrar(id_):
    cuota = g.bd.obtener(Cuota, id_)
    if cuota and not cuota.pagada:
        with g.bd.transaccion():  # la cuota pagada y el apunte en caja, juntos
            cuota.pagada = True
            cuota.fecha_pago = date.today().isoformat()
            movimiento = cobrar("Cuota", f"Cuota {cuota.mes}", cuota.importe, cuota.socio)
        recibo_listo(movimiento)
        flash(f"Cobrados {cuota.importe} € a {cuota.socio.nombre} ({cuota.mes}, {movimiento.forma}).", "ok")
    destino = request.form.get("volver")
    if destino and destino.isdigit():
        return volver("ficha", id_=int(destino))
    return volver("cuotas")


@app.post("/cuotas/generar")
@requiere("cuotas")
def cuotas_generar():
    mes = request.form.get("mes", "").strip()
    if len(mes) != 7 or mes[4] != "-":
        flash("El mes debe tener el formato AAAA-MM.", "error")
        return volver("cuotas")
    creadas = 0
    try:
        with g.bd.transaccion():  # o se generan las de todos, o ninguna
            ya_tienen = {c.socio_id for c in g.bd.consulta(Cuota).filtrar(mes=mes)}
            for socio in g.bd.consulta(Socio).filtrar(activo=True):
                if socio.id not in ya_tienen:
                    g.bd.agregar(Cuota(socio=socio, mes=mes, importe=socio.importe_cuota()))
                    creadas += 1
        flash(f"Generadas {creadas} cuotas de {mes} con la tarifa y el descuento de cada socio.", "ok")
    except ErrorORM as e:
        flash(f"No se generó ninguna cuota: {motivo(e)}", "error")
    return volver("cuotas", ver="todas")


@app.route("/cuotas/remesa.csv")
@requiere("datos_bancarios")
def remesa():
    """Fichero para el banco: cuotas pendientes de un mes de los socios que pagan por domiciliación."""
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    g.bd.consulta(Socio).todos()
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(["referencia", "socio", "dni", "iban", "importe", "concepto"])
    total = 0
    for cuota in g.bd.consulta(Cuota).filtrar(mes=mes).filtrar(pagada=False).ordenar("socio_id"):
        s = cuota.socio
        if s.activo and s.forma_pago == "Domiciliación" and s.iban:
            escritor.writerow([f"CUOTA-{cuota.id:06d}", s.nombre, s.dni, s.iban, cuota.importe,
                               f"Cuota {mes} {NOMBRE_CLUB}"])
            total += cuota.importe
    escritor.writerow(["", "TOTAL", "", "", total, ""])
    # ﻿ al principio: así Excel abre bien las tildes
    return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=remesa_{mes}.csv"})


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

@app.route("/informe")
@requiere("informe")
def informe():
    # Aquí sí se usa SQL escrito a mano: consultas de informe con JOIN y GROUP BY
    deudas = g.bd.sql(
        "SELECT socios.id, socios.nombre, equipos.nombre AS equipo, COUNT(*) AS cuotas, SUM(cuotas.importe) AS deuda "
        "FROM cuotas JOIN socios ON cuotas.socio_id = socios.id JOIN equipos ON socios.equipo_id = equipos.id "
        "WHERE cuotas.pagada = ? GROUP BY socios.id, socios.nombre, equipos.nombre ORDER BY deuda DESC", (0,))
    recaudacion = g.bd.sql(
        "SELECT mes, COUNT(*) AS cobradas, SUM(importe) AS total FROM cuotas WHERE pagada = ? "
        "GROUP BY mes ORDER BY mes", (1,))
    por_equipo = g.bd.sql(
        "SELECT equipos.nombre, equipos.categoria, COUNT(*) AS socios FROM socios "
        "JOIN equipos ON socios.equipo_id = equipos.id WHERE socios.activo = ? "
        "GROUP BY equipos.nombre, equipos.categoria ORDER BY socios DESC", (1,))
    por_pago = g.bd.sql(
        "SELECT forma_pago, COUNT(*) AS socios FROM socios WHERE activo = ? GROUP BY forma_pago ORDER BY socios DESC", (1,))
    por_seccion = g.bd.sql(
        "SELECT equipos.deporte, COUNT(*) AS socios FROM socios JOIN equipos ON socios.equipo_id = equipos.id "
        "WHERE socios.activo = ? GROUP BY equipos.deporte ORDER BY socios DESC", (1,))
    ingresos = g.bd.sql("SELECT tipo, COUNT(*) AS cobros, SUM(importe) AS total FROM movimientos "
                        "GROUP BY tipo ORDER BY total DESC")
    return render_template("informe.html", deudas=deudas, recaudacion=recaudacion, por_equipo=por_equipo,
                           por_pago=por_pago, por_seccion=por_seccion, ingresos=ingresos,
                           total_ingresos=sum(f["total"] for f in ingresos))


# ---------------------------------------------------------------------------
# Usuarios (solo Administrador)
# ---------------------------------------------------------------------------

@app.route("/usuarios", methods=["GET", "POST"])
@requiere("usuarios")
def usuarios():
    equipos = g.bd.consulta(Equipo).ordenar("id").todos()
    if request.method == "POST":
        try:
            nombre_usuario = request.form.get("usuario", "").strip().lower()
            if g.bd.consulta(Usuario).filtrar(usuario=nombre_usuario).contar():
                raise ErrorORM(f"ya existe el usuario '{nombre_usuario}'")
            nuevo = Usuario(nombre=request.form.get("nombre", "").strip(), usuario=nombre_usuario,
                            rol=request.form.get("rol", "Secretaría"))
            if nuevo.rol == "Entrenador":
                nuevo.equipo = g.bd.obtener(Equipo, int(request.form.get("equipo", 0)))
            nuevo.poner_clave(request.form.get("clave", ""))
            g.bd.agregar(nuevo)
            g.bd.confirmar()
            flash(f"Usuario '{nuevo.usuario}' creado ({nuevo.rol}).", "ok")
            return volver("usuarios")
        except (ErrorORM, ValueError) as e:
            g.bd.deshacer()
            flash(f"No se pudo crear: {motivo(e)}", "error")
    lista = g.bd.consulta(Usuario).ordenar("nombre").todos()
    return render_template("usuarios.html", usuarios=lista, equipos=equipos, roles=ROLES, valores=request.form)


@app.post("/usuarios/<int:id_>/activo")
@requiere("usuarios")
def usuario_activo(id_):
    usuario = g.bd.obtener(Usuario, id_)
    if usuario is None:
        abort(404)
    if usuario.id == g.usuario.id:
        flash("No puedes desactivar tu propio usuario.", "error")
    else:
        usuario.activo = not usuario.activo
        g.bd.confirmar()
        flash(f"Usuario '{usuario.usuario}' {'activado' if usuario.activo else 'desactivado: ya no puede entrar'}.", "ok")
    return volver("usuarios")


@app.post("/usuarios/<int:id_>/clave")
@requiere("usuarios")
def usuario_nueva_clave(id_):
    usuario = g.bd.obtener(Usuario, id_)
    if usuario is None:
        abort(404)
    temporal = secrets.token_urlsafe(6)  # contraseña provisional aleatoria
    usuario.poner_clave(temporal)
    g.bd.confirmar()
    flash(f"Nueva contraseña provisional de '{usuario.usuario}': {temporal}  (que la cambie en 'Mi cuenta').", "ok")
    return volver("usuarios")


# ---------------------------------------------------------------------------
# Actividades (equipos y grupos)
# ---------------------------------------------------------------------------

@app.route("/actividades", methods=["GET", "POST"])
def actividades():
    if request.method == "POST":
        if not g.usuario.puede("editar_socios"):
            abort(403)
        try:
            id_ = int(request.form.get("id") or 0)
            grupo = g.bd.obtener(Equipo, id_) if id_ else Equipo(nombre=request.form.get("nombre", "").strip(),
                                                                  categoria=request.form.get("categoria", "").strip() or "General")
            if not id_:
                grupo.deporte = request.form.get("deporte", "Fútbol")
            grupo.horario = request.form.get("horario", "").strip()
            grupo.entrenador = request.form.get("entrenador", "").strip()
            grupo.plazas = int(request.form.get("plazas") or 0)
            id_tarifa = int(request.form.get("tarifa") or 0)
            if id_tarifa:
                grupo.tarifa = g.bd.obtener(Tarifa, id_tarifa)
            if not id_:
                g.bd.agregar(grupo)
            g.bd.confirmar()
            flash(f"{'Grupo creado' if not id_ else 'Grupo actualizado'}: {grupo.nombre}.", "ok")
            return volver("actividades")
        except (ErrorORM, ValueError) as e:
            g.bd.deshacer()
            flash(f"No se ha guardado: {motivo(e)}", "error")
    g.bd.consulta(Tarifa).todos()
    grupos = g.bd.consulta(Equipo).ordenar("id").todos()
    ocupacion = {}
    for socio in g.bd.consulta(Socio).filtrar(activo=True).todos():
        ocupacion[socio.equipo_id] = ocupacion.get(socio.equipo_id, 0) + 1
    por_deporte = {}
    for grupo in grupos:
        por_deporte.setdefault(grupo.deporte or "Otros", []).append(grupo)
    return render_template("actividades.html", por_deporte=por_deporte, ocupacion=ocupacion, deportes=DEPORTES,
                           tarifas=g.bd.consulta(Tarifa).filtrar(activa=True).todos())


# ---------------------------------------------------------------------------
# Tarifas
# ---------------------------------------------------------------------------

@app.route("/tarifas", methods=["GET", "POST"])
@requiere("tarifas")
def tarifas():
    if request.method == "POST":
        try:
            nueva = Tarifa(nombre=request.form.get("nombre", "").strip(), importe=int(request.form.get("importe") or 0),
                           descripcion=request.form.get("descripcion", "").strip())
            g.bd.agregar(nueva)
            g.bd.confirmar()
            flash(f"Tarifa «{nueva.nombre}» creada: {nueva.importe} €/mes.", "ok")
            return volver("tarifas")
        except (ErrorORM, ValueError) as e:
            g.bd.deshacer()
            flash(f"No se pudo crear la tarifa: {motivo(e)}", "error")
    lista = g.bd.consulta(Tarifa).ordenar("importe").todos()
    equipos = g.bd.consulta(Equipo).ordenar("id").todos()
    # cuántos socios pagan cada tarifa (la suya o la de su equipo)
    uso = {t.id: 0 for t in lista}
    for socio in g.bd.consulta(Socio).filtrar(activo=True):
        if socio.tarifa_aplicada:
            uso[socio.tarifa_aplicada.id] = uso.get(socio.tarifa_aplicada.id, 0) + 1
    return render_template("tarifas.html", tarifas=lista, equipos=equipos, uso=uso)


@app.post("/tarifas/<int:id_>")
@requiere("tarifas")
def tarifa_editar(id_):
    tarifa = g.bd.obtener(Tarifa, id_)
    if tarifa:
        try:
            tarifa.importe = int(request.form.get("importe") or 0)
            tarifa.activa = request.form.get("activa") == "si"
            g.bd.confirmar()
            flash(f"Tarifa «{tarifa.nombre}»: {tarifa.importe} €/mes. Se aplicará a las próximas cuotas que se generen.", "ok")
        except (ErrorORM, ValueError) as e:
            g.bd.deshacer()
            flash(f"No se ha guardado: {motivo(e)}", "error")
    return volver("tarifas")


@app.post("/equipos/<int:id_>/tarifa")
@requiere("tarifas")
def equipo_tarifa(id_):
    equipo = g.bd.obtener(Equipo, id_)
    tarifa = g.bd.obtener(Tarifa, int(request.form.get("tarifa") or 0))
    if equipo and tarifa:
        equipo.tarifa = tarifa
        g.bd.confirmar()
        flash(f"{equipo.nombre} pasa a la tarifa {tarifa}.", "ok")
    return volver("tarifas")


# ---------------------------------------------------------------------------
# Reservas de pistas
# ---------------------------------------------------------------------------

@app.route("/reservas")
@requiere("ver_reservas")
def reservas():
    fecha = request.args.get("fecha", date.today().isoformat())
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        dia = date.today()
    deporte = request.args.get("deporte", "")
    consulta = g.bd.consulta(Instalacion).filtrar(activa=True).ordenar("id")
    if deporte:
        consulta = consulta.filtrar(deporte=deporte)
    pistas = consulta.todos()
    ids_pistas = {p.id for p in pistas}
    g.bd.consulta(Socio).todos()
    del_dia = [r for r in g.bd.consulta(Reserva).filtrar(fecha=dia.isoformat(), estado="Confirmada").todos()
               if r.instalacion_id in ids_pistas]
    # Cuadrante: para cada hora y pista, la reserva que la ocupa (o None si está libre)
    ocupado = {}
    for r in del_dia:
        for h in range(r.hora_inicio, r.hora_fin):
            ocupado[(h, r.instalacion_id)] = r
    horas = list(range(HORA_APERTURA, HORA_CIERRE))
    return render_template("reservas.html", dia=dia, pistas=pistas, horas=horas, ocupado=ocupado,
                           reservas_dia=sorted(del_dia, key=lambda r: (r.hora_inicio, r.instalacion_id)),
                           anterior=(dia - timedelta(days=1)).isoformat(), siguiente=(dia + timedelta(days=1)).isoformat(),
                           deporte=deporte, deportes=[d for d in DEPORTES if d != "Natación"])


@app.route("/reservas/nueva", methods=["GET", "POST"])
@requiere("reservas")
def reserva_nueva():
    pistas = g.bd.consulta(Instalacion).filtrar(activa=True).ordenar("id").todos()
    socios_activos = g.bd.consulta(Socio).filtrar(activo=True).ordenar("nombre").todos()
    datos = request.form if request.method == "POST" else request.args
    if request.method == "POST":
        try:
            id_socio = int(datos.get("socio") or 0)
            reserva = Reserva(instalacion=g.bd.obtener(Instalacion, int(datos["instalacion"])),
                              fecha=datos.get("fecha", ""), hora_inicio=int(datos.get("hora") or 0),
                              duracion=int(datos.get("duracion") or 1),
                              nombre_cliente=datos.get("nombre_cliente", "").strip(),
                              telefono=datos.get("telefono", "").strip(), creada_por=g.usuario)
            if id_socio:
                reserva.socio = g.bd.obtener(Socio, id_socio)
            reserva.importe = reserva.calcular_importe()
            with g.bd.transaccion():  # la reserva (y su cobro, si se paga ya), o nada
                g.bd.agregar(reserva)
                movimiento = None
                if datos.get("pagar_ahora") == "si":
                    reserva.pagada = True
                    movimiento = cobrar("Reserva", f"{reserva.instalacion.nombre} {reserva.fecha} "
                                        f"{reserva.hora_inicio}:00-{reserva.hora_fin}:00", reserva.importe, reserva.socio)
            if movimiento:
                recibo_listo(movimiento)
            flash(f"Reservada {reserva.instalacion.nombre} el {reserva.fecha} de {reserva.hora_inicio}:00 a "
                  f"{reserva.hora_fin}:00 para {reserva.cliente}: {reserva.importe} €"
                  f"{' (pagada)' if reserva.pagada else ' (pendiente de pago)'}.", "ok")
            return volver("reservas", fecha=reserva.fecha)
        except (ErrorORM, ValueError, KeyError) as e:
            flash(f"No se pudo reservar: {motivo(e)}", "error")
    return render_template("reserva_form.html", pistas=pistas, socios=socios_activos, datos=datos,
                           horas=list(range(HORA_APERTURA, HORA_CIERRE)))


@app.post("/reservas/<int:id_>/cobrar")
@requiere("reservas")
def reserva_cobrar(id_):
    reserva = g.bd.obtener(Reserva, id_)
    if reserva and not reserva.pagada and reserva.estado == "Confirmada":
        with g.bd.transaccion():
            reserva.pagada = True
            movimiento = cobrar("Reserva", f"{reserva.instalacion.nombre} {reserva.fecha} "
                                f"{reserva.hora_inicio}:00-{reserva.hora_fin}:00", reserva.importe, reserva.socio)
        recibo_listo(movimiento)
        flash(f"Cobrada la reserva de {reserva.cliente}: {reserva.importe} €.", "ok")
    return volver("reservas", fecha=reserva.fecha if reserva else None)


@app.post("/reservas/<int:id_>/cancelar")
@requiere("reservas")
def reserva_cancelar(id_):
    reserva = g.bd.obtener(Reserva, id_)
    if reserva and reserva.estado == "Confirmada":
        reserva.estado = "Cancelada"
        g.bd.confirmar()
        aviso = " Estaba pagada: recuerda devolver el importe." if reserva.pagada else ""
        flash(f"Reserva de {reserva.cliente} cancelada: la pista queda libre.{aviso}", "ok")
    return volver("reservas", fecha=reserva.fecha if reserva else None)


# ---------------------------------------------------------------------------
# Tienda de equipaciones
# ---------------------------------------------------------------------------

@app.route("/tienda")
@requiere("tienda")
def tienda():
    ver = request.args.get("ver", "abiertos")
    productos = g.bd.consulta(Producto).ordenar("id").todos()
    g.bd.consulta(Socio).todos()
    consulta = g.bd.consulta(Pedido).ordenar("-id")
    pedidos = [p for p in consulta.todos() if ver == "todos" or p.estado in ("Pendiente de pago", "Pagado")]
    socios_activos = g.bd.consulta(Socio).filtrar(activo=True).ordenar("nombre").todos()
    return render_template("tienda.html", productos=productos, pedidos=pedidos, socios=socios_activos, ver=ver)


@app.post("/tienda/pedido")
@requiere("tienda")
def pedido_nuevo():
    try:
        producto = g.bd.obtener(Producto, int(request.form["producto"]))
        socio = g.bd.obtener(Socio, int(request.form["socio"]))
        cantidad = int(request.form.get("cantidad") or 1)
        pedido = Pedido(socio=socio, producto=producto, talla=request.form.get("talla", "").strip(),
                        cantidad=cantidad, importe=producto.precio * cantidad, fecha=date.today().isoformat())
        with g.bd.transaccion():  # el pedido, el stock y el cobro: todo o nada
            producto.stock -= cantidad          # si no hay stock, antes_de_guardar() lo impide
            g.bd.agregar(pedido)
            movimiento = None
            if request.form.get("pagar_ahora") == "si":
                pedido.estado = "Pagado"
                movimiento = cobrar("Equipación", f"{producto.nombre} talla {pedido.talla} x{cantidad}",
                                    pedido.importe, socio)
        if movimiento:
            recibo_listo(movimiento)
        flash(f"Pedido de {socio.nombre}: {cantidad} × {producto.nombre} ({pedido.talla}) = {pedido.importe} €. "
              f"Quedan {producto.stock} en stock.", "ok")
    except (ErrorORM, ValueError, KeyError) as e:
        flash(f"No se pudo hacer el pedido: {motivo(e)}", "error")
    return volver("tienda")


@app.post("/tienda/pedidos/<int:id_>/<accion>")
@requiere("tienda")
def pedido_accion(id_, accion):
    pedido = g.bd.obtener(Pedido, id_)
    if pedido is None:
        abort(404)
    try:
        if accion == "cobrar" and pedido.estado == "Pendiente de pago":
            with g.bd.transaccion():
                pedido.estado = "Pagado"
                movimiento = cobrar("Equipación", f"{pedido.producto.nombre} talla {pedido.talla} x{pedido.cantidad}",
                                    pedido.importe, pedido.socio)
            recibo_listo(movimiento)
            flash(f"Cobrado el pedido de {pedido.socio.nombre}: {pedido.importe} €.", "ok")
        elif accion == "entregar" and pedido.estado == "Pagado":
            pedido.estado = "Entregado"
            g.bd.confirmar()
            flash(f"Pedido entregado a {pedido.socio.nombre}.", "ok")
        elif accion == "cancelar" and pedido.estado == "Pendiente de pago":
            with g.bd.transaccion():  # se cancela y vuelve al stock
                pedido.estado = "Cancelado"
                pedido.producto.stock += pedido.cantidad
            flash(f"Pedido cancelado: {pedido.cantidad} × {pedido.producto.nombre} vuelve al stock.", "ok")
    except ErrorORM as e:
        flash(f"No se pudo: {motivo(e)}", "error")
    return volver("tienda")


@app.post("/tienda/productos/<int:id_>")
@requiere("tienda")
def producto_editar(id_):
    producto = g.bd.obtener(Producto, id_)
    if producto:
        try:
            producto.precio = int(request.form.get("precio") or 0)
            producto.stock = int(request.form.get("stock") or 0)
            producto.tallas = request.form.get("tallas", "").strip()
            g.bd.confirmar()
            flash(f"{producto.nombre} actualizado.", "ok")
        except (ErrorORM, ValueError) as e:
            g.bd.deshacer()
            flash(f"No se ha guardado: {motivo(e)}", "error")
    return volver("tienda")


@app.post("/tienda/productos")
@requiere("tienda")
def producto_nuevo():
    try:
        producto = Producto(nombre=request.form.get("nombre", "").strip(), precio=int(request.form.get("precio") or 0),
                            tallas=request.form.get("tallas", "").strip(), stock=int(request.form.get("stock") or 0))
        g.bd.agregar(producto)
        g.bd.confirmar()
        flash(f"Producto «{producto.nombre}» añadido al catálogo.", "ok")
    except (ErrorORM, ValueError) as e:
        g.bd.deshacer()
        flash(f"No se pudo añadir: {motivo(e)}", "error")
    return volver("tienda")


# ---------------------------------------------------------------------------
# Caja y recibos
# ---------------------------------------------------------------------------

@app.route("/caja")
@requiere("caja")
def caja():
    fecha = request.args.get("fecha", date.today().isoformat())
    g.bd.consulta(Usuario).todos()
    g.bd.consulta(Socio).todos()
    movimientos = g.bd.consulta(Movimiento).filtrar(fecha=fecha).ordenar("id").todos()
    por_forma = g.bd.sql("SELECT forma, COUNT(*) AS cobros, SUM(importe) AS total FROM movimientos "
                         "WHERE fecha = ? GROUP BY forma ORDER BY total DESC", (fecha,))
    por_tipo = g.bd.sql("SELECT tipo, COUNT(*) AS cobros, SUM(importe) AS total FROM movimientos "
                        "WHERE fecha = ? GROUP BY tipo ORDER BY total DESC", (fecha,))
    total = sum(m.importe for m in movimientos)
    return render_template("caja.html", fecha=fecha, movimientos=movimientos, por_forma=por_forma,
                           por_tipo=por_tipo, total=total)


@app.route("/recibo/<int:id_>")
@requiere("caja")
def recibo(id_):
    movimiento = g.bd.obtener(Movimiento, id_)
    if movimiento is None:
        abort(404)
    return render_template("recibo.html", m=movimiento)


@app.context_processor
def datos_comunes():
    usuario = g.get("usuario")
    return {
        "club": NOMBRE_CLUB,
        "usuario": usuario,
        "ver_sql": usuario is not None and usuario.puede("ver_sql"),
        "sql_pagina": lambda: list(g.bd.registro) if "bd" in g else [],
        "sql_accion": session.pop("sql_accion", []),
        "recibo": session.pop("recibo", None),
        "formas_cobro": FORMAS_COBRO,
        "hoy_iso": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# Preparar la base de datos al arrancar
# ---------------------------------------------------------------------------

USUARIOS_DEMO = [
    # nombre, usuario, contraseña, rol, grupo que entrena
    ("Administración", "admin", "admin123", "Administrador", None),
    ("Laura Pastor (recepción)", "secretaria", "secretaria123", "Secretaría", None),
    ("Rosa Gil", "rosa", "rosa1234", "Entrenador", "Alevín A"),
    ("Toni Vidal", "toni", "toni1234", "Entrenador", "Infantil A"),
    ("Marta Climent", "marta", "marta1234", "Entrenador", "Natación Iniciación"),
]


def crear_usuario(bd, nombre, login, clave, rol, grupo=None):
    usuario = Usuario(nombre=nombre, usuario=login, rol=rol)
    if grupo is not None:
        usuario.equipo = grupo
    usuario.poner_clave(clave)
    bd.agregar(usuario)
    print(f"    {rol:<14} usuario: {login:<11} contraseña: {clave}")
    return usuario


def preparar_base_de_datos(reiniciar=False):
    with Sesion(ruta_config=CONFIG) as bd:
        bd.mostrar_sql = False
        if reiniciar:
            print("  borrando la base de datos para cargar el polideportivo de demostración...")
            bd.borrar_tablas(*TODOS)
        for cambio in bd.migrar(*TODOS):  # crea tablas o añade columnas nuevas SIN perder datos
            if not reiniciar:
                print("  migración:", cambio)

        if bd.consulta(Equipo).contar() == 0:
            # Base de datos vacía: se carga un polideportivo completo de demostración
            print("  usuarios de demostración (cambia las contraseñas en 'Mi cuenta'):")
            usuarios = [crear_usuario(bd, *datos[:4]) for datos in USUARIOS_DEMO if datos[4] is None]
            bd.confirmar()
            print("  generando el polideportivo de demostración (tarda unos segundos)...")
            resumen = datos_polideportivo.cargar(bd, usuario_caja=usuarios[1])
            for nombre, login, clave, rol, grupo in USUARIOS_DEMO:
                if grupo is not None:
                    crear_usuario(bd, nombre, login, clave, rol, bd.consulta(Equipo).filtrar(nombre=grupo).primero())
            bd.confirmar()
            print("  cargado: " + ", ".join(f"{n} {k}" for k, n in resumen.items()))
            return

        # Base de datos de una versión anterior: completar lo que falte, sin borrar nada
        if bd.consulta(Tarifa).contar() == 0:
            tarifas = crear_tarifas()
            bd.agregar(*tarifas)
            bd.confirmar()
            for equipo in bd.consulta(Equipo).todos():
                if equipo.tarifa_id is None:
                    equipo.tarifa = tarifas[2] if equipo.categoria == "Senior" else tarifas[0]
            bd.confirmar()
        if bd.consulta(Instalacion).contar() == 0:
            bd.agregar(*crear_instalaciones(), *crear_productos())
            bd.confirmar()
        if bd.consulta(Usuario).contar() == 0:
            print("  usuarios de demostración (cambia las contraseñas en 'Mi cuenta'):")
            for nombre, login, clave, rol, grupo in USUARIOS_DEMO:
                equipo = bd.consulta(Equipo).filtrar(nombre=grupo).primero() if grupo else None
                if grupo is None or equipo is not None:
                    crear_usuario(bd, nombre, login, clave, rol, equipo)
            bd.confirmar()


if __name__ == "__main__":
    # python web_club.py --reiniciar  -> borra todo y carga el polideportivo de demostración
    preparar_base_de_datos(reiniciar="--reiniciar" in sys.argv)
    print(f"{NOMBRE_CLUB} · Club Manager funcionando en  http://localhost:5000   (Ctrl + C para parar)")
    # threaded=False: una petición cada vez, porque cada una arranca su propio motor
    app.run(port=5000, debug=False, threaded=False)
