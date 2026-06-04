# gestor.py
from datetime import date
from clases import Ciudad, Pueblo, Barrio, Fiesta, DiaFiesta, Localidad

class GestorMunicipios:
    def __init__(self):
        self.ciudades: list[Ciudad] = []
        self.pueblos: list[Pueblo] = []

    def crear_ciudad(self, nombre: str, desc_corta: str, desc_larga: str) -> Ciudad:
        ciudad = Ciudad(nombre, desc_corta, desc_larga)
        self.ciudades.append(ciudad)
        return ciudad

    def crear_pueblo(self, nombre: str, desc_corta: str, desc_larga: str) -> Pueblo:
        pueblo = Pueblo(nombre, desc_corta, desc_larga)
        self.pueblos.append(pueblo)
        return pueblo

    def crear_barrio(self, ciudad: Ciudad, nombre: str, desc_corta: str, desc_larga: str) -> Barrio:
        barrio = Barrio(nombre, desc_corta, desc_larga)
        ciudad.add_barrio(barrio)
        return barrio

    def crear_fiesta(self, entidad: Localidad, nombre: str, desc_corta: str, desc_larga: str) -> Fiesta:
        fiesta = Fiesta(nombre, desc_corta, desc_larga)
        entidad.add_fiesta(fiesta)
        return fiesta

    def crear_dia_fiesta(self, fiesta: Fiesta, fecha: date, nombre: str, programacion: str) -> DiaFiesta:
        dia = DiaFiesta(fecha, nombre, programacion)
        fiesta.add_dia(dia)
        return dia

    def __repr__(self):
        return (f"GestorMunicipios(ciudades={len(self.ciudades)}, pueblos={len(self.pueblos)})")
