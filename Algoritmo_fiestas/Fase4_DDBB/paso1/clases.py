# tipos.py
from datetime import date
from typing import List, Optional

class DiaFiesta:
    def __init__(self,  nombre: str, programacion: str, fecha:date):
        
        self.nombre = nombre
        self.programacion = programacion
        self.fecha=fecha

    def __repr__(self):
        return f"DiaFiesta(fecha={self.fecha}, nombre={self.nombre!r}, programacion={self.programacion!r})"

class Fiesta:
    def __init__(self, nombre: str, descripcion_corta: str, descripcion_larga: str, fechainicio:date,fechafin:date):
        self.nombre = nombre
        self.descripcion_corta = descripcion_corta
        self.descripcion_larga = descripcion_larga
        self.fechainicio =fechainicio
        self.fechafin=fechafin
        self.dias: List[DiaFiesta] = []

    def add_dia(self, dia: DiaFiesta):
        self.dias.append(dia)

    def __repr__(self):
        return f"Fiesta(nombre={self.nombre!r}, dias={len(self.dias)})"

class Localidad:
    def __init__(self, nombre: str, descripcion_corta: str, descripcion_larga: str,coordenadas: str, location:str,poblacion:int):
        self.nombre = nombre
        self.descripcion_corta = descripcion_corta
        self.descripcion_larga = descripcion_larga
        self.coordenadas= coordenadas
        self.location= location
        self.poblacion=poblacion
        self.fiestas: List[Fiesta] = []

    def add_fiesta(self, fiesta: Fiesta):
        self.fiestas.append(fiesta)

    def __repr__(self):
        return f"Localidad(nombre={self.nombre!r}, type={self.__class__.__name__}),fiestas={len(self.fiestas)})"

class Pueblo(Localidad):
    pass

class Barrio(Localidad):
    pass

class Ciudad(Localidad):
    pass

