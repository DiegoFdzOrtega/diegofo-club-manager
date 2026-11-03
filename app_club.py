"""
app_club.py — Demo de "diegofo | estadio" + estadio_orm: gestión de un club deportivo.

Ejecutar desde la carpeta RA3 (después de  pip install -e .):
    python app_club.py
"""

import estadio_orm
from estadio_orm import ErrorORM, Sesion
from datos_ejemplo import crear_equipos, crear_socios, cuotas_de
from modelos import TODOS, Cuota, Equipo, Socio


def titulo(texto):
    print()
    print("=" * 66)
    print(texto)
    print("=" * 66)


def main():
    # ------------------------------------------------------------------ (a)
    titulo("1. INSTALACIÓN DE LA HERRAMIENTA ORM")
    print(f"estadio_orm {estadio_orm.__version__} instalado en:")
    print(f"  {estadio_orm.__file__}")

    # ------------------------------------------------------------------ (b)
    titulo("2. CONFIGURACIÓN (estadio.ini)")
    sesion = Sesion()  # lee estadio.ini, arranca el motor y se conecta
    print(sesion.configuracion)

    try:
        demo(sesion)
    finally:
        # ---------------------------------------------------- Cierre
        titulo("9. CIERRE")
        sesion.cerrar()
        print("Sesión cerrada: el motor se ha detenido.")


def demo(sesion):
    # ------------------------------------------------------------------ (c)
    titulo("3. MAPEO: de clases de Python a tablas (lo genera el ORM)")
    sesion.borrar_tablas(*TODOS)  # empezar de cero en cada demo
    sesion.crear_tablas(*TODOS)
    print()
    for modelo in TODOS:
        columnas = ", ".join(f"{n}->{c.columna}" for n, c in modelo._campos.items())
        print(f"{modelo.__name__:<7} -> tabla '{modelo._tabla}':  {columnas}")

    # ------------------------------------------------------------------ (d)
    titulo("4. PERSISTENCIA: guardar objetos")
    alevin, infantil, senior = crear_equipos()
    socios = crear_socios(alevin, infantil, senior)  # datos inventados: ver datos_ejemplo.py
    print("Objetos creados en Python. ¿Tienen id?", [s.id for s in socios])
    sesion.agregar(*socios)  # los equipos se añaden solos (en cascada)
    print()
    sesion.confirmar()
    print()
    print("Después de confirmar(), la base de datos les ha dado id:")
    for s in socios:
        print(f"  {s.id}  {s.nombre:<14} -> {s.equipo}")

    print()
    print("Cuotas de octubre (pagada) y noviembre (pendiente) para todos:")
    for s in socios:
        sesion.agregar(*cuotas_de(s))
    sesion.mostrar_sql = False   # 12 INSERT: no hace falta verlos todos
    sesion.confirmar()
    sesion.mostrar_sql = True
    print(f"  {sesion.consulta(Cuota).contar()} cuotas guardadas")

    # ------------------------------------------------------------------ (e)
    titulo("5. RECUPERAR Y MODIFICAR OBJETOS")
    nora = sesion.obtener(Socio, 3)
    print(f"obtener(Socio, 3) -> {nora!r}")
    print(f"Mapa de identidad: ¿es el mismo objeto de antes? {nora is socios[2]}")
    print()
    print("Ficha de Nora (datos calculados por el modelo, no guardados):")
    print(f"  edad: {nora.edad}  categoría por edad: {nora.categoria_edad}  ¿menor?: {nora.es_menor}")
    print(f"  pago: {nora.forma_pago}  IBAN: {nora.iban_oculto}")

    print()
    print("Validaciones del modelo (no llegan a la base de datos):")
    for campo, valor in [("dni", "12345678A"), ("iban", "ES00 1234 5678 9012 3456 7890"),
                         ("fecha_nacimiento", "31/02/2015"), ("forma_pago", "Bizum")]:
        try:
            setattr(nora, campo, valor)
        except ErrorORM as e:
            print(f"  {campo + ' = ' + repr(valor):<50} -> {e}")
    try:
        nora.tutor = ""
        sesion.confirmar()
    except ErrorORM as e:
        print(f"  {'tutor = (vacío) siendo menor de edad':<50} -> {e}")
        sesion.deshacer()

    print()
    print("Nora cambia de email y de teléfono. Solo se actualiza lo que ha cambiado:")
    nora.email = "nora.peris@correo.es"
    nora.telefono = "600 333 333"
    sesion.confirmar()

    print()
    print("Relaciones en las dos direcciones:")
    print(f"  nora.equipo -> {nora.equipo}")
    for equipo in sesion.consulta(Equipo).ordenar("id"):
        nombres = ", ".join(s.nombre for s in equipo.socios)
        print(f"  {equipo.nombre}.socios -> {nombres}")

    print()
    print("Baja de un socio: se borran primero sus cuotas y después él")
    mario = sesion.consulta(Socio).filtrar(nombre="Mario Sanz").primero()
    for cuota in mario.cuotas:
        sesion.borrar(cuota)
    sesion.borrar(mario)
    sesion.confirmar()
    print(f"  ¿Sigue Mario en la base de datos? {sesion.obtener(Socio, mario.id) is not None}")

    print()
    print("Intento de borrar un equipo que tiene socios (lo impide la clave foránea):")
    sesion.borrar(senior)
    try:
        sesion.confirmar()
    except ErrorORM as e:
        print(f"  ERROR controlado: {e}")
        sesion.deshacer()

    # ------------------------------------------------------------------ (f)
    titulo("6. CONSULTAS")
    print("a) Con el ORM (sin escribir SQL):")
    pendientes = sesion.consulta(Cuota).filtrar(pagada=False).filtrar("importe", ">=", 40).ordenar("socio_id").todos()
    for c in pendientes:
        print(f"  {c.socio.nombre:<14} debe {c.importe} € de {c.mes}")
    encontrados = sesion.consulta(Socio).buscar("nombre", "ar").ordenar("nombre").todos()
    print(f"  Socios con 'ar' en el nombre: {', '.join(s.nombre for s in encontrados)}")

    print()
    print("b) Con SQL escrito a mano (JOIN + GROUP BY): deuda por socio")
    deudas = sesion.sql(
        "SELECT socios.nombre, equipos.nombre AS equipo, SUM(cuotas.importe) AS deuda, COUNT(*) AS cuotas "
        "FROM cuotas JOIN socios ON cuotas.socio_id = socios.id JOIN equipos ON socios.equipo_id = equipos.id "
        "WHERE cuotas.pagada = ? GROUP BY socios.nombre, equipos.nombre ORDER BY deuda DESC",
        (0,),
    )
    print(f"  {'Socio':<15}{'Equipo':<13}{'Cuotas':>7}{'Deuda':>8}")
    for fila in deudas:
        print(f"  {fila['nombre']:<15}{fila['equipo']:<13}{fila['cuotas']:>7}{fila['deuda']:>7} €")

    print()
    print("c) SQL a mano que devuelve objetos: socios dados de alta antes de 2025")
    veteranos = sesion.sql_objetos(Socio, "SELECT * FROM socios WHERE fecha_alta < ? ORDER BY fecha_alta", ("2025-01-01",))
    for s in veteranos:
        print(f"  {s.nombre:<14} socio desde {s.fecha_alta}")

    # ------------------------------------------------------------------ (g)
    titulo("7. TRANSACCIONES")
    print("a) Cobrar todas las cuotas de noviembre de un equipo (todo junto):")
    with sesion.transaccion():
        for socio in senior.socios:
            for cuota in socio.cuotas:
                if cuota.mes == "2026-11" and not cuota.pagada:
                    cuota.pagada = True
    total = sum(c.importe for c in sesion.consulta(Cuota).filtrar(pagada=True).filtrar(mes="2026-11"))
    print(f"  Cobrado en noviembre: {total} €")

    print()
    print("b) Alta de un socio con su primera cuota, pero la cuota es incorrecta:")
    antes = sesion.consulta(Socio).contar()
    try:
        with sesion.transaccion():
            nuevo = Socio(nombre="Hugo Bernat", email="hugo@correo.es", fecha_alta="2026-11-01", equipo=alevin)
            sesion.agregar(nuevo)
            cuota = Cuota(socio=nuevo, mes="2026-11", importe=30)
            cuota.importe = "treinta"   # error: debe ser un número
            sesion.agregar(cuota)
    except ErrorORM as e:
        print(f"  ERROR: {e}")
        print("  -> se deshace TODO, también el alta del socio")
    print(f"  Socios antes: {antes}   Socios después: {sesion.consulta(Socio).contar()}")

    print()
    print("c) Error de la base de datos a mitad de confirmar(): ROLLBACK automático")
    antes = sesion.consulta(Cuota).contar()
    try:
        with sesion.transaccion():
            sesion.agregar(Cuota(socio=socios[0], mes="2026-12", importe=30))
            fantasma = Cuota(socio_id=999, mes="2026-12", importe=30)  # el socio 999 no existe
            sesion.agregar(fantasma)
    except ErrorORM as e:
        print(f"  ERROR: {e}")
    print(f"  Cuotas antes: {antes}   Cuotas después: {sesion.consulta(Cuota).contar()}")

    # ------------------------------------------------------------- Resumen
    titulo("8. RESUMEN DEL CLUB")
    sesion.mostrar_sql = False
    for equipo in sesion.consulta(Equipo).ordenar("id"):
        print(f"{equipo.nombre:<12} {equipo.categoria:<9} entrenador: {equipo.entrenador:<12} "
              f"socios: {len(equipo.socios)}")
    print(f"Socios activos: {sesion.consulta(Socio).filtrar(activo=True).contar()}   "
          f"Cuotas pendientes: {sesion.consulta(Cuota).filtrar(pagada=False).contar()}")


if __name__ == "__main__":
    try:
        main()
    except ErrorORM as e:
        print("Error:", e)
