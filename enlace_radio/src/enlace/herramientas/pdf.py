"""Construcción del PDF con ReportLab (platypus)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

_FUENTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
try:
    pdfmetrics.registerFont(TTFont("DejaVu", str(_FUENTES / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FUENTES / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(_FUENTES / "DejaVuSans-Oblique.ttf")))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique", boldItalic="DejaVu-Bold")
    F, FB = "DejaVu", "DejaVu-Bold"
except Exception:  # pragma: no cover
    F, FB = "Helvetica", "Helvetica-Bold"

AZUL = colors.HexColor("#1f4e79")
GRIS = colors.HexColor("#f2f2f2")
VERDE = colors.HexColor("#d5f0dc")
ROJO = colors.HexColor("#f8d7da")
AMARILLO = colors.HexColor("#fff3cd")

_base = getSampleStyleSheet()
EST = {
    "titulo": ParagraphStyle("titulo", parent=_base["Title"], fontName=FB, fontSize=20, leading=25, textColor=AZUL),
    "subtitulo": ParagraphStyle("subtitulo", parent=_base["Normal"], fontName=F, fontSize=12, leading=16,
                                alignment=TA_CENTER, textColor=colors.HexColor("#444444")),
    "h1": ParagraphStyle("h1", parent=_base["Heading1"], fontName=FB, fontSize=14, leading=18, textColor=AZUL,
                         spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName=FB, fontSize=11.5, leading=15, textColor=AZUL,
                         spaceBefore=8, spaceAfter=4),
    "p": ParagraphStyle("p", parent=_base["Normal"], fontName=F, fontSize=9.5, leading=13.2, alignment=TA_JUSTIFY,
                        spaceAfter=5),
    "vi": ParagraphStyle("vi", parent=_base["Normal"], fontName=F, fontSize=9.5, leading=13, leftIndent=12,
                         bulletIndent=2, spaceAfter=2),
    "celda": ParagraphStyle("celda", parent=_base["Normal"], fontName=F, fontSize=7.8, leading=9.6),
    "celdab": ParagraphStyle("celdab", parent=_base["Normal"], fontName=FB, fontSize=7.8, leading=9.6,
                             textColor=colors.white),
    "pie": ParagraphStyle("pie", parent=_base["Normal"], fontName=F, fontSize=8, leading=10, alignment=TA_CENTER,
                          textColor=colors.HexColor("#555555"), spaceAfter=8),
    "caja": ParagraphStyle("caja", parent=_base["Normal"], fontName=F, fontSize=10, leading=14),
}


class Documento(SimpleDocTemplate):
    def __init__(self, ruta: Path, titulo: str, **kw):
        super().__init__(str(ruta), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.0 * cm,
                         bottomMargin=1.8 * cm, title=titulo, author="Sistema multiagente de diseño de radioenlaces",
                         subject="Informe técnico generado automáticamente", **kw)
        self.titulo = titulo

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ("h1", "h2"):
            nivel = 0 if flowable.style.name == "h1" else 1
            texto = flowable.getPlainText()
            clave = f"h{id(flowable)}"
            self.canv.bookmarkPage(clave)
            self.canv.addOutlineEntry(texto, clave, level=nivel)
            self.notify("TOCEntry", (nivel, texto, self.page, clave))


def _encabezado(canv, doc):
    canv.saveState()
    canv.setFont(F, 7.5)
    canv.setFillColor(colors.HexColor("#666666"))
    if doc.page > 1:
        canv.drawString(2 * cm, A4[1] - 1.2 * cm, doc.titulo[:110])
        canv.line(2 * cm, A4[1] - 1.3 * cm, A4[0] - 2 * cm, A4[1] - 1.3 * cm)
    canv.drawString(2 * cm, 1.0 * cm, "Generado automáticamente por el sistema multiagente · "
                    + dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    canv.drawRightString(A4[0] - 2 * cm, 1.0 * cm, f"Página {doc.page}")
    canv.restoreState()


class Constructor:
    """Acumula elementos (flowables) y numera secciones, figuras y tablas."""

    def __init__(self, ruta: Path, titulo: str):
        self.ruta = Path(ruta)
        self.doc = Documento(self.ruta, titulo)
        self.e: list = []
        self.n_sec = 0
        self.n_sub = 0
        self.n_fig = 0
        self.n_tab = 0

    def portada(self, titulo: str, subtitulo: str, lineas: list[str], veredicto: str, cumple: bool):
        self.e += [Spacer(1, 3 * cm), Paragraph(titulo, EST["titulo"]), Spacer(1, 0.4 * cm),
                   Paragraph(subtitulo, EST["subtitulo"]), Spacer(1, 1.2 * cm)]
        caja = Table([[Paragraph(veredicto, EST["caja"])]], colWidths=[15.5 * cm])
        caja.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), VERDE if cumple else ROJO),
                                  ("BOX", (0, 0), (-1, -1), 1, AZUL), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                  ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        self.e += [caja, Spacer(1, 1.2 * cm)]
        for l in lineas:
            self.e.append(Paragraph(l, EST["subtitulo"]))
        self.e.append(PageBreak())
        toc = TableOfContents()
        toc.levelStyles = [ParagraphStyle("t1", fontName=FB, fontSize=10, leading=14, leftIndent=10),
                           ParagraphStyle("t2", fontName=F, fontSize=9, leading=12, leftIndent=26)]
        self.e += [Paragraph("Contenido", EST["h1"].clone("toc_t")), toc, PageBreak()]

    def seccion(self, titulo: str):
        self.n_sec += 1
        self.n_sub = 0
        self.e.append(Paragraph(f"{self.n_sec}. {titulo}", EST["h1"]))

    def anexo(self, letra: str, titulo: str):
        self.e.append(Paragraph(f"Anexo {letra}. {titulo}", EST["h1"]))

    def sub(self, titulo: str):
        self.n_sub += 1
        self.e.append(Paragraph(f"{self.n_sec}.{self.n_sub} {titulo}", EST["h2"]))

    def p(self, texto: str):
        for parrafo in [t for t in texto.split("\n\n") if t.strip()]:
            self.e.append(Paragraph(parrafo.strip(), EST["p"]))

    def vinetas(self, items: list[str]):
        for it in items:
            self.e.append(Paragraph(it, EST["vi"], bulletText="•"))
        self.e.append(Spacer(1, 4))

    def figura(self, ruta: Path, pie: str, ancho_cm: float = 16.0):
        self.n_fig += 1
        img = Image(str(ruta))
        r = img.imageHeight / img.imageWidth
        img.drawWidth = ancho_cm * cm
        img.drawHeight = ancho_cm * cm * r
        self.e.append(KeepTogether([img, Paragraph(f"<b>Figura {self.n_fig}.</b> {pie}", EST["pie"])]))

    def tabla(self, filas: list[list], titulo: str, anchos: list[float] | None = None, resaltar: dict | None = None,
              fuente: str | None = None):
        self.n_tab += 1
        datos = [[Paragraph(str(c), EST["celdab"]) for c in filas[0]]]
        datos += [[Paragraph(str(c), EST["celda"]) for c in fila] for fila in filas[1:]]
        t = Table(datos, colWidths=[a * cm for a in anchos] if anchos else None, repeatRows=1, hAlign="CENTER")
        est = [("BACKGROUND", (0, 0), (-1, 0), AZUL), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
               ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        for i in range(1, len(datos)):
            if i % 2 == 0:
                est.append(("BACKGROUND", (0, i), (-1, i), GRIS))
        for i, color in (resaltar or {}).items():
            est.append(("BACKGROUND", (0, i), (-1, i), {"verde": VERDE, "amarillo": AMARILLO}.get(color, ROJO)))
        t.setStyle(TableStyle(est))
        pie = f"<b>Tabla {self.n_tab}.</b> {titulo}" + (f" Fuente: {fuente}" if fuente else "")
        self.e += [Paragraph(pie, EST["pie"]), t, Spacer(1, 8)]

    def salto(self):
        self.e.append(PageBreak())

    def construir(self) -> Path:
        self.doc.multiBuild(self.e, onFirstPage=_encabezado, onLaterPages=_encabezado)
        return self.ruta
