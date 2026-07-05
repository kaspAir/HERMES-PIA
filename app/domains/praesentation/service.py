"""Erzeugt die Präsentation für Auftraggeber/Projektausschuss aus dem
hochgeladenen (freigabebereiten) PIA.

Vorlagenlogik: Es wird auf der hochgeladenen .pptx aufgebaut (Folienmaster,
Theme, Foliengrösse bleiben erhalten; vorhandene Folien der Vorlage bleiben
vorne stehen, die generierten Folien werden angehängt). Ohne Vorlage dient
eine leere Standard-Präsentation als Basis. Die Folien werden bewusst mit
eigenen Textrahmen auf dem "leersten" Layout gebaut – das funktioniert mit
jeder Vorlage, auch mit einer komplett leeren Präsentation.
"""
import io
import json
import re

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Emu, Pt

from app.domains.praesentation.parser import parse_pia

# Ampelfarben der Risikomatrix (dezent, an Excel-Klassiker angelehnt).
_GRUEN = RGBColor(0xC6, 0xEF, 0xCE)
_GELB = RGBColor(0xFF, 0xEB, 0x9C)
_ROT = RGBColor(0xFF, 0xC7, 0xCE)
_GRAU = RGBColor(0xF2, 0xF2, 0xF2)


class PraesentationService:

    def __init__(self, llm=None):
        self.llm = llm

    def generate_from_docx(self, pia_bytes, template_bytes=None,
                           fallback_name="Projekt", datum=""):
        """PIA-.docx + optionale .pptx-Vorlage -> Präsentation (BytesIO)."""
        pia = parse_pia(pia_bytes)
        if not pia.get("projektname"):
            pia["projektname"] = fallback_name

        prs = Presentation(io.BytesIO(template_bytes)) if template_bytes else Presentation()
        if not len(prs.slide_layouts):
            raise ValueError("Die Vorlage enthält keine Folienlayouts.")
        b = _Builder(prs)

        b.titel(pia, datum)
        b.ausgangslage(pia, self._ausgangslage_bullets(pia))
        b.ziele(pia)
        b.termine(pia)
        b.personalaufwand(pia)
        b.kosten(pia)
        b.risiken(pia)
        b.antrag(pia)

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf

    # ---- Zusammenfassung (LLM mit deterministischem Fallback) --------- #

    def _ausgangslage_bullets(self, pia):
        text = (pia.get("ausgangslage") or "").strip()
        if not text:
            return []
        if self.llm:
            try:
                raw = self.llm.complete(
                    "Du fasst die Ausgangslage eines Projektinitialisierungsauftrags "
                    "fuer eine Praesentation vor Auftraggeber und Projektausschuss "
                    "zusammen. Sachlicher Behoerdenstil, keine Erfindungen, keine "
                    "Ergaenzungen - nur, was im Text steht. Antworte ausschliesslich "
                    "mit validem JSON.",
                    [{"role": "user", "content":
                        f"Ausgangslage:\n{text}\n\n"
                        'Gib 3-5 praegnante Stichpunkte (je max. 15 Woerter) als '
                        'JSON zurueck: {"bullets": ["...", "..."]}'}],
                    max_tokens=600,
                )
                m = re.search(r"\{.*\}", raw, re.S)
                data = json.loads(m.group()) if m else {}
                bullets = [str(x).strip() for x in data.get("bullets", []) if str(x).strip()]
                if bullets:
                    return bullets[:5]
            except Exception:  # noqa: BLE001 – Fallback übernimmt
                pass
        # Fallback: erste Sätze (ohne Komplexitätsblock).
        haupt = text.split("Komplexitätseinschätzung")[0]
        saetze = [s.strip() for s in re.split(r"(?<=[.!?])\s+", haupt) if s.strip()]
        return saetze[:4]


# ---------------------------------------------------------------------- #
# Folienbau                                                                #
# ---------------------------------------------------------------------- #

class _Builder:

    def __init__(self, prs):
        self.prs = prs
        # "Leerstes" Layout: am wenigsten Platzhalter -> funktioniert mit jeder Vorlage.
        self.layout = min(prs.slide_layouts, key=lambda lay: len(lay.placeholders))
        self.sw = prs.slide_width
        self.sh = prs.slide_height

    # ---- Grundgerüst --------------------------------------------------- #

    def _slide(self, titel):
        slide = self.prs.slides.add_slide(self.layout)
        box = slide.shapes.add_textbox(self._x(0.06), self._y(0.05),
                                       self._x(0.88), self._y(0.12))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = titel
        p.font.size = Pt(26)
        p.font.bold = True
        return slide

    def _x(self, frac):
        return Emu(int(self.sw * frac))

    def _y(self, frac):
        return Emu(int(self.sh * frac))

    def _bullets(self, slide, items, top=0.22, size=16):
        box = slide.shapes.add_textbox(self._x(0.06), self._y(top),
                                       self._x(0.88), self._y(0.92 - top))
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for item in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.text = f"•  {item}"
            p.font.size = Pt(size)
            p.space_after = Pt(8)
        return box

    # ---- Folien --------------------------------------------------------- #

    def titel(self, pia, datum):
        slide = self.prs.slides.add_slide(self.layout)
        box = slide.shapes.add_textbox(self._x(0.06), self._y(0.28),
                                       self._x(0.88), self._y(0.4))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = pia.get("projektname") or "Projekt"
        p.font.size = Pt(36)
        p.font.bold = True
        sub = tf.add_paragraph()
        sub.text = "Projektinitialisierungsauftrag – Antrag auf Projektinitialisierungsfreigabe"
        sub.font.size = Pt(18)
        zeile3 = []
        if pia.get("projektleiter"):
            zeile3.append(f"Projektleitung: {pia['projektleiter']}")
        if pia.get("auftraggeber"):
            zeile3.append(f"Auftraggeber/in: {pia['auftraggeber']}")
        if datum:
            zeile3.append(datum)
        if zeile3:
            meta = tf.add_paragraph()
            meta.text = "  ·  ".join(zeile3)
            meta.font.size = Pt(14)

    def ausgangslage(self, pia, bullets):
        if not bullets:
            return
        slide = self._slide("Ausgangslage")
        self._bullets(slide, bullets)

    def ziele(self, pia):
        ziele = pia.get("ziele") or []
        if not ziele:
            return
        slide = self._slide("Ziele der Phase Initialisierung")
        items = [_kurz(z["beschreibung"], 160) for z in ziele[:6]]
        self._bullets(slide, items, size=14)

    def termine(self, pia):
        termine = pia.get("termine") or []
        if not termine:
            return
        slide = self._slide("Ergebnisse und Termine")
        rows = termine[:10]
        table = slide.shapes.add_table(
            len(rows) + 1, 3, self._x(0.06), self._y(0.2),
            self._x(0.88), self._y(0.05 * (len(rows) + 1)),
        ).table
        for c, kopf in enumerate(("Lieferergebnis", "Termin", "Abnahme durch")):
            cell = table.cell(0, c)
            cell.text = kopf
            cell.text_frame.paragraphs[0].font.size = Pt(12)
            cell.text_frame.paragraphs[0].font.bold = True
        for r, row in enumerate(rows, 1):
            werte = (_kurz(row["ergebnis"], 80), row.get("termin", ""), row.get("abnahme", ""))
            meilenstein = "meilenstein" in row["ergebnis"].lower()
            for c, wert in enumerate(werte):
                cell = table.cell(r, c)
                cell.text = wert
                p = cell.text_frame.paragraphs[0]
                p.font.size = Pt(11)
                p.font.bold = meilenstein

    def personalaufwand(self, pia):
        personal = [p for p in (pia.get("personalaufwand") or []) if p.get("aufwand")]
        if not personal:
            return
        slide = self._slide("Personalaufwand der Initialisierung (PT)")
        data = CategoryChartData()
        data.categories = [_kurz(p["rolle"], 40) for p in personal]
        data.add_series("PT", [p["aufwand"] for p in personal])
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.BAR_CLUSTERED, self._x(0.06), self._y(0.2),
            self._x(0.88), self._y(0.68), data,
        )
        chart = frame.chart
        chart.has_legend = False
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(11)

    def kosten(self, pia):
        kosten = pia.get("kosten") or []
        einzel = [k for k in kosten
                  if k.get("betrag") and not _ist_summe(k["position"])]
        summen = [k for k in kosten if k.get("betrag") and _ist_summe(k["position"])]
        if not einzel and not summen:
            return
        slide = self._slide("Kosten der Initialisierung (CHF inkl. MwSt.)")
        if einzel:
            data = CategoryChartData()
            data.categories = [_kurz(k["position"], 45) for k in einzel]
            data.add_series("CHF", [k["betrag"] for k in einzel])
            frame = slide.shapes.add_chart(
                XL_CHART_TYPE.PIE, self._x(0.06), self._y(0.2),
                self._x(0.55), self._y(0.65), data,
            )
            chart = frame.chart
            chart.has_legend = True
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
            chart.legend.font.size = Pt(10)
        if summen:
            box = slide.shapes.add_textbox(self._x(0.64), self._y(0.25),
                                           self._x(0.32), self._y(0.5))
            tf = box.text_frame
            tf.word_wrap = True
            first = True
            for s in summen:
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = f"{s['position']}: CHF {s['betrag']:,}".replace(",", "'")
                p.font.size = Pt(13)
                p.font.bold = "total" in s["position"].lower()
                p.space_after = Pt(6)

    def risiken(self, pia):
        risiken = pia.get("risiken") or []
        if not risiken:
            return
        platzierbar = [r for r in risiken if r.get("ew") and r.get("ag")]
        if platzierbar:
            self._risikomatrix(platzierbar)
        slide = self._slide("Wesentliche Risiken der Initialisierung")
        items = [f"R{r['nr']}: {_kurz(r['beschreibung'], 150)}" for r in risiken[:6]]
        self._bullets(slide, items, size=13)

    def _risikomatrix(self, risiken):
        slide = self._slide("Risikomatrix (Initialisierung)")
        stufen = ("Tief", "Mittel", "Hoch")
        table = slide.shapes.add_table(
            4, 4, self._x(0.14), self._y(0.2), self._x(0.72), self._y(0.6),
        ).table
        table.cell(0, 0).text = "EW \\ AG"
        for c, s in enumerate(stufen, 1):
            table.cell(0, c).text = s
        for r, s in enumerate(reversed(stufen), 1):   # EW: hoch oben
            table.cell(r, 0).text = s
        for r in range(4):
            for c in range(4):
                cell = table.cell(r, c)
                p = cell.text_frame.paragraphs[0]
                p.font.size = Pt(12)
                if r == 0 or c == 0:
                    p.font.bold = True
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = _GRAU
                else:
                    ew = 4 - r          # Zeile 1 = EW hoch (3) ... Zeile 3 = tief (1)
                    ag = c
                    score = ew * ag
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = (
                        _ROT if score >= 6 else _GELB if score >= 3 else _GRUEN)
        for risiko in risiken:
            r = 4 - risiko["ew"]
            c = risiko["ag"]
            cell = table.cell(r, c)
            bestehend = cell.text_frame.paragraphs[0].text
            neu = f"R{risiko['nr']}"
            cell.text_frame.paragraphs[0].text = (
                f"{bestehend}  {neu}".strip() if bestehend else neu)
            cell.text_frame.paragraphs[0].font.size = Pt(14)
            cell.text_frame.paragraphs[0].font.bold = True

    def antrag(self, pia):
        slide = self._slide("Antrag an den Auftraggeber")
        items = [
            "Der Projektinitialisierungsauftrag liegt in der vorliegenden Fassung zur "
            "Freigabe vor.",
            "Antrag: Erteilung der Projektinitialisierungsfreigabe und Start der "
            "Phase Initialisierung.",
        ]
        naechste = [t for t in (pia.get("termine") or [])
                    if "meilenstein" in t.get("ergebnis", "").lower()]
        for t in naechste[:2]:
            zeile = f"{t['ergebnis']}"
            if t.get("termin"):
                zeile += f" – geplant {t['termin']}"
            items.append(zeile)
        self._bullets(slide, items, size=16)


def _kurz(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _ist_summe(position):
    p = (position or "").lower()
    return "summe" in p or "total" in p
