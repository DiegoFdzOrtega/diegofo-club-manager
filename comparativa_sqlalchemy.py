"""
comparativa_sqlalchemy.py
El MISMO club hecho con SQLAlchemy, el ORM más usado de Python, sobre SQLite.
Sirve para comparar mi estadio_orm con una herramienta profesional.

Antes de ejecutar:   pip install sqlalchemy
Ejecutar:            python comparativa_sqlalchemy.py
"""

import os

from sqlalchemy import ForeignKey, String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


# ---------------------------------------------------------------------------
# Mapeo (equivale a modelos.py)
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Equipo(Base):
    __tablename__ = "equipos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40))
    categoria: Mapped[str] = mapped_column(String(20))
    socios: Mapped[list["Socio"]] = relationship(back_populates="equipo")


class Socio(Base):
    __tablename__ = "socios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    equipo: Mapped[Equipo] = relationship(back_populates="socios")
    cuotas: Mapped[list["Cuota"]] = relationship(back_populates="socio")


class Cuota(Base):
    __tablename__ = "cuotas"
    id: Mapped[int] = mapped_column(primary_key=True)
    socio_id: Mapped[int] = mapped_column(ForeignKey("socios.id"))
    mes: Mapped[str] = mapped_column(String(7))
    importe: Mapped[int]
    pagada: Mapped[bool] = mapped_column(default=False)
    socio: Mapped[Socio] = relationship(back_populates="cuotas")


def titulo(texto):
    print()
    print("=" * 66)
    print(texto)
    print("=" * 66)


def main():
    # Configuración: la "cadena de conexión" dice qué base de datos usar
    titulo("1. CONFIGURACIÓN Y MAPEO")
    fichero = "club_sqlalchemy.db"
    if os.path.exists(fichero):
        os.remove(fichero)
    motor = create_engine(f"sqlite:///{fichero}")
    Base.metadata.create_all(motor)  # crea las tablas a partir de las clases
    print(f"Base de datos: {motor.url}")
    print("Tablas creadas:", ", ".join(Base.metadata.tables))

    titulo("2. PERSISTENCIA")
    with Session(motor) as sesion:
        alevin = Equipo(nombre="Alevín A", categoria="Alevín")
        senior = Equipo(nombre="Senior", categoria="Senior")
        socios = [
            Socio(nombre="Lucía Martí", equipo=alevin),
            Socio(nombre="Mario Sanz", equipo=alevin),
            Socio(nombre="Adrián Gómez", equipo=senior),
            Socio(nombre="Carla Ibáñez", equipo=senior),
        ]
        sesion.add_all(socios)
        for s in socios:
            importe = 40 if s.equipo is senior else 30
            sesion.add_all([Cuota(socio=s, mes="2026-10", importe=importe, pagada=True),
                            Cuota(socio=s, mes="2026-11", importe=importe)])
        sesion.commit()
        print("Socios guardados con id:", [(s.id, s.nombre) for s in socios])

        titulo("3. RECUPERAR Y MODIFICAR")
        lucia = sesion.get(Socio, 1)
        lucia.nombre = "Lucía Martí Ros"
        sesion.commit()
        print(f"get(Socio, 1) -> {lucia.nombre}, equipo {lucia.equipo.nombre}")
        print(f"senior.socios -> {[s.nombre for s in senior.socios]}")

        titulo("4. CONSULTAS")
        consulta = select(Socio).where(Socio.nombre.like("%ar%")).order_by(Socio.nombre)
        print("Con 'ar' en el nombre:", [s.nombre for s in sesion.scalars(consulta)])

        deudas = sesion.execute(
            select(Socio.nombre, func.sum(Cuota.importe).label("deuda"))
            .join(Cuota.socio)
            .where(Cuota.pagada.is_(False))
            .group_by(Socio.nombre)
            .order_by(func.sum(Cuota.importe).desc())
        ).all()
        print("Deuda por socio (ORM):", [(n, d) for n, d in deudas])

        filas = sesion.execute(text("SELECT COUNT(*) FROM cuotas WHERE pagada = 0")).scalar()
        print("Cuotas pendientes (SQL a mano):", filas)

        titulo("5. TRANSACCIONES")
        antes = sesion.scalar(select(func.count()).select_from(Cuota))
        try:
            sesion.add(Cuota(socio=lucia, mes="2026-12", importe=30))
            sesion.flush()  # el INSERT ya se ha enviado...
            raise ValueError("pago rechazado por el banco")
        except ValueError as e:
            sesion.rollback()  # ...pero se deshace
            print("Error:", e, "-> ROLLBACK")
        despues = sesion.scalar(select(func.count()).select_from(Cuota))
        print(f"Cuotas antes: {antes}   Cuotas después: {despues}")

    motor.dispose()  # cerrar las conexiones


if __name__ == "__main__":
    main()
