from fastapi import FastAPI
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import unicodedata


app = FastAPI()

# ---------------------------------------------------------
# REQUEST MODEL (slug ya NO es obligatorio)
# ---------------------------------------------------------
class FichaRequest(BaseModel):
    url: str
    slug: str | None = None


# ---------------------------------------------------------
# UTILIDADES GENÉRICAS
# ---------------------------------------------------------

def clean(t):
    if not t:
        return "No especificado"
    t = re.sub(r"\s+", " ", t.replace("\n", " ").replace("\t", " ").strip())
    if "preg" in t.lower():
        return "No especificado"
    return t


def slugify(text):
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def extract_by_keywords(soup, keywords):
    tags = soup.find_all(["li", "p", "span", "div", "td", "th"])

    for tag in tags:
        txt = tag.get_text(" ", strip=True).lower()

        for kw in keywords:
            if kw in txt:
                # caso "campo: valor"
                if ":" in txt:
                    return clean(txt.split(":", 1)[1])

                # caso "2 garages"
                num = re.findall(r"\d+", txt)
                if num:
                    return num[0]

                return clean(txt)

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
    text = soup.get_text(" ", strip=True)
    m = re.search(r"\$\s?[Uu]?\s?\d[\d\.\s]*", text)
    if m:
        return clean(m.group(0))

    return extract_by_keywords(soup, ["precio", "valor"])


def get_operation(soup):
    text = soup.get_text(" ", strip=True).lower()
    if "alquiler" in text:
        return "Alquiler"
    if "venta" in text:
        return "Venta"
    if "tempor" in text:
        return "Temporal"

    return extract_by_keywords(soup, ["operación"])


def get_property_type(soup):
    return extract_by_keywords(soup, [
        "tipo de propiedad", "tipo de inmueble", "apartamento",
        "casa", "local", "monoambiente"
    ])


def get_location(soup):
    return extract_by_keywords(soup, [
        "ubicación", "zona", "barrio", "departamento"
    ])


def get_dormitorios(soup):
    return extract_by_keywords(soup, ["dormitorios", "cuartos", "habitaciones"])


def get_banos(soup):
    return extract_by_keywords(soup, ["baño", "baños"])


def get_superficie(soup):
    return extract_by_keywords(soup, ["superficie", "m2", "metros", "área"])


def get_estado(soup):
    return extract_by_keywords(soup, ["estado"])


def get_gastos(soup):
    return extract_by_keywords(soup, ["gastos comunes", "expensas"])


def get_orientacion(soup):
    return extract_by_keywords(soup, ["orientación", "frente", "contrafrente", "este", "oeste", "norte", "sur"])


def get_anio_construccion(soup):
    return extract_by_keywords(soup, ["año de construcción", "antigüedad"])


def get_piso(soup):
    return extract_by_keywords(soup, ["piso", "planta"])


def get_disposicion(soup):
    return extract_by_keywords(soup, ["contrafrente", "frente"])


def get_calefaccion(soup):
    return extract_by_keywords(soup, ["calefacción", "estufa", "radiadores"])


def get_ascensor(soup):
    return extract_by_keywords(soup, ["ascensor"])


def get_seguridad(soup):
    return extract_by_keywords(soup, ["seguridad", "vigilancia", "portero"])


def get_referencia(soup):
    return extract_by_keywords(soup, ["referencia", "ref"])


def get_mascotas(soup):
    val = extract_by_keywords(soup, ["mascotas", "pet", "acepta mascotas"])
    if val.lower() in ["si", "sí", "acepta", "permitido"]:
        return "Sí"
    if val.lower() in ["no", "no acepta"]:
        return "No"
    return val


def get_mobiliario(soup):
    text = soup.get_text(" ", strip=True).lower()
    if "amoblado" in text or "amueblado" in text:
        return "Amueblado"

    return extract_by_keywords(soup, ["mobiliario", "amueblado"])


def get_cochera(soup):
    keywords = ["garage", "garaje", "cochera", "estacionamiento", "parking"]

    val = extract_by_keywords(soup, keywords)
    if val != "No especificado":
        return val

    full = soup.get_text(" ", strip=True).lower()

    m = re.search(r"(garage|cochera)[^\d]{0,10}(\d+)", full)
    if m:
        return m.group(2)

    m = re.search(r"(\d+)\s+(garage|cochera)", full)
    if m:
        return m.group(1)

    for k in keywords:
        if k in full:
            return "Sí"

    return "No especificado"


def get_imagenes(soup):
    urls = set()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            urls.add(src)

    for s in soup.find_all("source"):
        src = s.get("srcset")
        if src:
            urls.add(src.split(" ")[0])

    return list(urls)


def get_descripcion(soup):
    parrafos = soup.find_all("p")
    textos = [
        clean(p.get_text(" ", strip=True))
        for p in parrafos
        if len(p.get_text(strip=True)) > 60
    ]
    if textos:
        return " ".join(textos)
    return "No especificado"


# ---------------------------------------------------------
# SCRAPE PRINCIPAL
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
        "anio_construccion": get_anio_construccion(soup),
        "orientacion": get_orientacion(soup),
        "piso": get_piso(soup),
        "disposicion": get_disposicion(soup),
        "calefaccion": get_calefaccion(soup),
        "ascensor": get_ascensor(soup),
        "seguridad": get_seguridad(soup),
        "referencia": get_referencia(soup),
        "mascotas": get_mascotas(soup),
        "mobiliario": get_mobiliario(soup),
        "descripcion": get_descripcion(soup),
        "imagenes": get_imagenes(soup),
    }


# ---------------------------------------------------------
# ENDPOINT PRINCIPAL
# ---------------------------------------------------------

@app.post("/crear-ficha")
def crear_ficha(req: FichaRequest):

    datos = scrape(req.url)

    # generar slug automáticamente si no se envía
    if not req.slug:
        req.slug = slugify(datos.get("titulo", "propiedad"))

    return {
        "ok": True,
        "slug": req.slug,
        "ficha": datos
    }
