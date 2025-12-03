from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re

app = FastAPI()

class FichaRequest(BaseModel):
    url: str
    slug: str


# ---------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------

def clean(t):
    if not t:
        return "No especificado"
    t = re.sub(r'\s+', ' ', t.replace("\n", " ").replace("\t", " ").strip())
    if "preg" in t.lower():
        return "No especificado"
    return t


def extract_number(text):
    matches = re.findall(r"\d+", text)
    return matches[0] if matches else "No especificado"


def match_by_keywords(soup, keywords):
    """
    Busca valores con formato "label: valor" o tablas.
    """
    tags = soup.find_all(["li", "p", "span", "div", "td", "th"])
    for tag in tags:
        txt = tag.get_text(" ", strip=True).lower()
        for kw in keywords:
            if kw in txt:
                # Caso label: valor
                if ":" in txt:
                    return clean(txt.split(":", 1)[1])
                # Caso "Garage 1" o "1 Garage"
                num = extract_number(txt)
                if num != "No especificado":
                    return num
                return "Sí"
    return "No especificado"


# ---------------------------------------------------------
# EXTRACTORES ESPECÍFICOS
# ---------------------------------------------------------

def get_title(soup):
    h1 = soup.find("h1")
    if h1:
        return clean(h1.text)
    return "No especificado"


def get_price(soup):
    text = soup.get_text(" ", strip=True).lower()
    m = re.search(r"\$\s?u?s?\s?\d[\d\.\s]*", text)
    if m:
        return clean(m.group(0))
    return match_by_keywords(soup, ["precio", "valor"])


def get_operation(soup):
    text = soup.get_text(" ", strip=True).lower()
    if "alquiler" in text:
        return "Alquiler"
    if "venta" in text:
        return "Venta"
    if "tempor" in text:
        return "Temporal"
    return match_by_keywords(soup, ["operación", "tipo de operación"])


def get_property_type(soup):
    return match_by_keywords(soup, ["tipo de propiedad", "tipo de inmueble", "apartamento", "casa", "local", "monoambiente"])


def get_location(soup):
    return match_by_keywords(soup, ["ubicación", "zona", "barrio", "departamento"])


def get_dormitorios(soup):
    txt = match_by_keywords(soup, ["dormitorios", "dormitorio", "cuartos", "habitaciones"])
    return txt


def get_banos(soup):
    return match_by_keywords(soup, ["baño", "baños", "bath"])


def get_superficie(soup):
    text = match_by_keywords(soup, ["superficie", "m2", "metros", "área"])
    return text


def get_estado(soup):
    return match_by_keywords(soup, ["estado", "condición"])


def get_gastos(soup):
    return match_by_keywords(soup, ["gastos comunes", "expensas"])


def get_mascotas(soup):
    val = match_by_keywords(soup, ["mascotas", "pet friendly"])
    if val.lower() in ["si", "sí", "acepta", "permitido"]:
        return "Sí"
    if val.lower() in ["no", "no acepta"]:
        return "No"
    return val


def get_mobiliario(soup):
    text = soup.get_text(" ", strip=True).lower()
    if "amoblado" in text or "amueblado" in text:
        return "Amueblado"
    return match_by_keywords(soup, ["mobiliario", "amueblado"])


def get_orientacion(soup):
    return match_by_keywords(soup, ["orientación", "orientacion", "frente", "contrafrente", "este", "oeste", "norte", "sur"])


def get_anio(soup):
    return match_by_keywords(soup, ["año de construcción", "antigüedad"])


def get_cochera(soup):
    keywords = ["cochera", "garage", "garaje", "estacionamiento", "parking", "parqueo"]
    val = match_by_keywords(soup, keywords)

    if val != "No especificado":
        return val

    # búsqueda avanzada en texto completo
    full = soup.get_text(" ", strip=True).lower()

    # patrones como "garage para 2 autos"
    m = re.search(r"(garage|cochera|estacionamiento)[^\d]{0,10}(\d+)", full)
    if m:
        return m.group(2)

    # "2 garages"
    m = re.search(r"(\d+)\s+(garage|cochera|estacionamiento)", full)
    if m:
        return m.group(1)

    # si solo aparece la palabra → Sí
    for kw in keywords:
        if kw in full:
            return "Sí"

    return "No especificado"


def get_imagenes(soup):
    urls = set()

    # <img src="">
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            urls.add(src)

    # <source srcset="">
    for s in soup.find_all("source"):
        src = s.get("srcset")
        if src:
            parts = [p.strip() for p in src.split(",")]
            for p in parts:
                u = p.split(" ")[0]
                if u.startswith("http"):
                    urls.add(u)

    return list(urls)


def get_descripcion(soup):
    # Buscar párrafos largos
    parrafos = soup.find_all("p")
    textos = [p.get_text(" ", strip=True) for p in parrafos if len(p.get_text(strip=True)) > 80]
    if textos:
        return clean(" ".join(textos))

    return "No especificado"


# ---------------------------------------------------------
# SCRAPPER PRINCIPAL
# ---------------------------------------------------------

def scrape(url):
    html = requests.get(url, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    return {
        "titulo": get_title(soup),
        "operacion": get_operation(soup),
        "tipo_propiedad": get_property_type(soup),
        "precio": get_price(soup),
        "ubicacion": get_location(soup),
        "dormitorios": get_dormitorios(soup),
        "banos": get_banos(soup),
        "superficie": get_superficie(soup),
        "estado": get_estado(soup),
        "gastos_comunes": get_gastos(soup),
        "cochera": get_cochera(soup),
        "anio_construccion": get_anio(soup),
        "orientacion": get_orientacion(soup),
        "mascotas": get_mascotas(soup),
        "mobiliario": get_mobiliario(soup),
        "descripcion": get_descripcion(soup),
        "imagenes": get_imagenes(soup),
    }


# ---------------------------------------------------------
# FASTAPI ENDPOINT
# ---------------------------------------------------------

@app.post("/crear-ficha")
def crear_ficha(req: FichaRequest):
    datos = scrape(req.url)

    return {
        "ok": True,
        "slug": req.slug,
        "ficha": datos
    }
