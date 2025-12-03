from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()

class FichaRequest(BaseModel):
    url: str
    slug: str

# ----------------------------------------------------------
# Funciones utilitarias
# ----------------------------------------------------------

def limpiar_texto(t):
    if not t:
        return "No especificado"
    t = t.replace("\n", " ").replace("\t", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t

def normalizar_valor(v):
    if not v or "preg" in v.lower():
        return "No especificado"
    return limpiar_texto(v)

# ----------------------------------------------------------
# EXTRAER COCHERA / GARAGE DE MANERA INTELIGENTE
# ----------------------------------------------------------

def extraer_cochera(soup):
    """
    Detecta variantes:
    garage, garajes, cochera, estacionamiento, parking, parqueo, etc.
    """
    patrones = [
        r"cochera",
        r"garage",
        r"garajes",
        r"estacionamiento",
        r"parking",
        r"parqueo",
        r"espacio.*auto",
        r"autos?",
    ]

    texto_total = soup.get_text(separator=" ").lower()

    # 1) Buscar frases como "1 garage", "2 cocheras", etc.
    for p in patrones:
        match = re.search(rf"(\d+)\s+{p}", texto_total)
        if match:
            return match.group(1)

    # 2) Buscar campos en tablas o listas de características
    labels = soup.find_all(["li", "div", "span", "p", "td", "th"])

    for lbl in labels:
        t = lbl.get_text(" ", strip=True).lower()
        for p in patrones:
            if p in t:
                # Caso "Garage: No", "Garajes: 2", etc
                if ":" in t:
                    valor = t.split(":", 1)[1].strip()
                    return normalizar_valor(valor)
                # Caso de solo la palabra → es cochera pero sin detalle
                return "Sí"

    # 3) Si no aparece ninguna referencia
    return "No especificado"


# ----------------------------------------------------------
# SCRAPPER GENÉRICO
# ----------------------------------------------------------

def scrappear(url):
    r = requests.get(url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    # Extraer cochera
    cochera = extraer_cochera(soup)

    # ------------------------------------------------------
    # Aquí puedes agregar más extractores genéricos:
    # dormitorios, baños, superficie, etc.
    # ------------------------------------------------------

    data = {
        "titulo": "No especificado",
        "cochera": cochera,
        "imagenes": [],
    }

    # Título genérico
    title = soup.find("h1")
    if title:
        data["titulo"] = limpiar_texto(title.text)

    # Imágenes genéricas
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith("http"):
            data["imagenes"].append(src)

    return data


# ----------------------------------------------------------
# ENDPOINT PRINCIPAL
# ----------------------------------------------------------

@app.post("/crear-ficha")
def crear_ficha(req: FichaRequest):
    datos = scrappear(req.url)
    return {
        "ok": True,
        "slug": req.slug,
        "datos": datos
    }
