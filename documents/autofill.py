import os
import json
import hashlib
import base64
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.core.files.base import ContentFile
from django.forms.models import model_to_dict

from customers.models import CustomerProfile
from .models import CustomerDocument, DocumentTemplate


try:
    from docxtpl import DocxTemplate  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    DocxTemplate = None

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    from pypdf.generic import (  # type: ignore
        BooleanObject,
        IndirectObject,
        NameObject,
        TextStringObject,
    )
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None
    PdfWriter = None
    NameObject = None
    BooleanObject = None
    TextStringObject = None
    IndirectObject = None


def _autofill_debug_enabled() -> bool:
    """
    Debug-Ausgaben für Autofill (Prints) aktivieren.
    - Standard: aktiv, wenn Django DEBUG=True
    - Override: AUTOFILL_DEBUG=true/false
    """
    env_val = os.environ.get("AUTOFILL_DEBUG")
    if env_val is None or env_val == "":
        return bool(getattr(settings, "DEBUG", False))
    return env_val.lower() in ("1", "true", "yes", "y", "on")


def _autofill_debug_verbose() -> bool:
    """
    Verbose Debug-Mode: gibt große Payloads aus (z. B. Raw-Mappings).
    Aktivieren via AUTOFILL_DEBUG_VERBOSE=true
    """
    return os.environ.get("AUTOFILL_DEBUG_VERBOSE", "").lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


def _autofill_print(msg: str, data: Optional[Dict[str, Any]] = None, *, verbose_only: bool = False) -> None:
    if not _autofill_debug_enabled():
        return
    if verbose_only and not _autofill_debug_verbose():
        return
    if data:
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            payload = str(data)
        print(f"[AUTOFILL][DEBUG] {msg} {payload}")
    else:
        print(f"[AUTOFILL][DEBUG] {msg}")


def _safe_fill_pdf_form_fields(writer: Any, value_dict: Dict[str, Any]) -> Optional[str]:
    """
    Praxisbewährter PDF-AcroForm-Fix:
    - Werte in die Feld-Dictionaries schreiben ("/V" und optional "/DV")
    - "/NeedAppearances = true" setzen, damit der Viewer (Chrome/Adobe) rendert

    Wichtig: Wir verwenden bewusst NICHT `PdfWriter.update_page_form_field_values`,
    weil pypdf dabei (auch bei `auto_regenerate=False`) Appearances erzeugt und bei
    PDFs mit kaputten/fehlenden "/AP" (Appearance) abstürzen kann.

    Returns: None bei Erfolg, sonst Fehlertext.
    """
    if not value_dict:
        return None

    if BooleanObject is None or TextStringObject is None or NameObject is None:
        return "pypdf.generic Objekte nicht verfügbar (BooleanObject/TextStringObject/NameObject)."

    # NeedAppearances setzen (damit Viewer rendert)
    try:
        # set_need_appearances_writer benötigt /AcroForm im Root. Wenn es existiert, nutzen wir es.
        if hasattr(writer, "set_need_appearances_writer"):
            try:
                writer.set_need_appearances_writer(True)
            except Exception:
                pass
        # Fallback: direkt ins /AcroForm schreiben, falls vorhanden
        root = getattr(writer, "_root_object", None)
        if root and NameObject("/AcroForm") in root:
            acro = root[NameObject("/AcroForm")]
            try:
                acro[NameObject("/NeedAppearances")] = BooleanObject(True)
            except Exception:
                pass
    except Exception:
        pass

    try:
        pages = list(getattr(writer, "pages", []) or [])
        value_keys = list(value_dict.keys())
        _autofill_print(
            "PDF fill start",
            {"pages": len(pages), "value_keys": len(value_keys), "sample_keys": value_keys[:10]},
        )
        updated = 0
        matched_fields: List[str] = []
        unmatched_sample: List[str] = []
        matched_set: set[str] = set()

        for page in pages:
            annots = page.get("/Annots")
            if not annots:
                continue

            for annot_ref in annots:
                try:
                    annot = annot_ref.get_object()
                except Exception:
                    continue

                if annot.get("/Subtype") != "/Widget":
                    continue

                # Parent-Annotation bestimmen (ähnlich wie pypdf intern)
                if "/FT" in annot and "/T" in annot:
                    parent = annot
                else:
                    parent = annot.get("/Parent")
                    try:
                        parent = parent.get_object() if parent else annot
                    except Exception:
                        parent = annot

                # Feldname: bevorzugt qualified name, sonst /T
                qualified_name = None
                t_name = None
                if hasattr(writer, "_get_qualified_field_name"):
                    try:
                        qualified_name = writer._get_qualified_field_name(parent)
                    except Exception:
                        qualified_name = None

                try:
                    t = parent.get("/T") or annot.get("/T")
                    t_name = str(t) if t is not None else None
                except Exception:
                    t_name = None

                # Match-Strategie:
                # - Wenn value_dict qualified names enthält, nutzen wir sie
                # - Wenn value_dict nur /T-Namen enthält, matchen wir darauf
                field_name = None
                if qualified_name and qualified_name in value_dict:
                    field_name = qualified_name
                elif t_name and t_name in value_dict:
                    field_name = t_name

                if not field_name:
                    continue

                raw_value = value_dict[field_name]
                if raw_value is None:
                    continue

                # Feldtyp bestimmen (/Tx, /Btn, /Ch, ...)
                ft = None
                try:
                    ft = parent.get("/FT") or annot.get("/FT")
                except Exception:
                    ft = None
                ft_str = str(ft) if ft is not None else ""

                # Helper: bool-ish interpretieren
                def _boolish(v: Any) -> Optional[bool]:
                    if isinstance(v, bool):
                        return v
                    s = str(v).strip().lower()
                    if s in ("1", "true", "yes", "y", "ja", "on", "checked", "x"):
                        return True
                    if s in ("0", "false", "no", "n", "nein", "off", "unchecked", ""):
                        return False
                    return None

                # Helper: On-State für Checkbox/Radio bestimmen
                def _pick_on_state(a: Any) -> str:
                    try:
                        ap = a.get("/AP")
                        n = ap.get("/N") if ap else None
                        if n:
                            keys = list(getattr(n, "keys", lambda: [])())
                            # pypdf dict keys sind meist NameObjects wie "/Off", "/Yes"
                            for k in keys:
                                ks = str(k)
                                if ks != "/Off":
                                    return ks
                    except Exception:
                        pass
                    return "/Yes"

                # Helper: Optionen für /Ch
                def _choice_options(p: Any) -> List[str]:
                    try:
                        opt = p.get("/Opt")
                        if not opt:
                            return []
                        out: List[str] = []
                        for item in list(opt):
                            # item kann string oder [export, display] sein
                            try:
                                if isinstance(item, (list, tuple)) and item:
                                    out.append(str(item[0]))
                                else:
                                    out.append(str(item))
                            except Exception:
                                continue
                        return out
                    except Exception:
                        return []

                # Nur Werte setzen – keine Appearances generieren (NeedAppearances bleibt)
                try:
                    if ft_str == "/Btn":
                        b = _boolish(raw_value)
                        desired_on = None
                        if b is True:
                            desired_on = _pick_on_state(annot)
                        elif b is False:
                            desired_on = None
                        else:
                            # String: wenn es wie ein State aussieht, nutzen
                            sv = str(raw_value).strip()
                            if sv.startswith("/"):
                                desired_on = sv
                            else:
                                # z.B. "Yes"
                                desired_on = "/" + sv if sv else None

                        if desired_on:
                            parent[NameObject("/V")] = NameObject(desired_on)
                            parent[NameObject("/DV")] = NameObject(desired_on)
                            # Für Widgets: /AS setzen hilft bei vielen Viewern
                            try:
                                annot[NameObject("/AS")] = NameObject(desired_on)
                            except Exception:
                                pass
                        else:
                            parent[NameObject("/V")] = NameObject("/Off")
                            parent[NameObject("/DV")] = NameObject("/Off")
                            try:
                                annot[NameObject("/AS")] = NameObject("/Off")
                            except Exception:
                                pass
                    elif ft_str == "/Ch":
                        opts = _choice_options(parent)
                        sv = str(raw_value).strip()
                        chosen = None
                        if opts:
                            # exaktes Matching oder normalisiert
                            if sv in opts:
                                chosen = sv
                            else:
                                svn = _normalize_match_key(sv)
                                for o in opts:
                                    if _normalize_match_key(o) == svn:
                                        chosen = o
                                        break
                            # Index
                            if chosen is None:
                                try:
                                    idx = int(sv)
                                    if 0 <= idx < len(opts):
                                        chosen = opts[idx]
                                except Exception:
                                    pass
                        # Fallback: Text setzen (manche PDFs akzeptieren freie Eingabe)
                        if chosen is None:
                            chosen = sv
                        parent[NameObject("/V")] = TextStringObject(str(chosen))
                        parent[NameObject("/DV")] = TextStringObject(str(chosen))
                    else:
                        # Default: Text (/Tx und alles Unbekannte als String)
                        parent[NameObject("/V")] = TextStringObject(str(raw_value))
                        parent[NameObject("/DV")] = TextStringObject(str(raw_value))

                    updated += 1
                    if field_name not in matched_set:
                        matched_set.add(field_name)
                        if len(matched_fields) < 20:
                            matched_fields.append(field_name)
                except Exception:
                    # Wenn das Setzen scheitert, einfach weitermachen
                    continue

        if len(value_keys) and len(unmatched_sample) < 20:
            # Sample: Werte, für die kein Feld gefunden wurde
            for k in value_keys:
                if k not in matched_set:
                    unmatched_sample.append(k)
                    if len(unmatched_sample) >= 20:
                        break

        _autofill_print(
            "PDF fill result",
            {
                "updated_count": updated,
                "matched_unique_fields": len(matched_set),
                "matched_sample": matched_fields,
                "unmatched_sample": unmatched_sample,
                "unmatched_count": max(0, len(value_keys) - len(matched_set)),
            },
        )

        if updated == 0:
            return "Keine Felder wurden aktualisiert (kein Match zwischen Feldnamen und value_dict)."
        return None
    except Exception as exc:
        _autofill_print("PDF fill exception", {"error": str(exc)})
        return str(exc)


@dataclass
class MappingEntry:
    template_field: str
    customer_key: Optional[str]
    value: Optional[str]
    confidence: float
    status: str  # "filled" oder "missing"
    field_id: Optional[str] = None


@dataclass
class PdfFieldDescriptor:
    """
    Stabile Descriptoren für PDF-AcroForm-Widget-Felder.

    Wichtig: `field_id` ist bewusst ein "Code/Selector" ohne Klartext-Feldnamen,
    damit die KI nur über `field_id` antworten kann, ohne Feldnamen zu leaken.
    """

    field_id: str
    field_name: str
    label_hint: str
    field_type: Optional[str]
    page_index: int
    rect: Optional[List[float]]
    widget_ref: Optional[str]
    parent_ref: Optional[str]


def _pdf_indirect_ref_code(obj: Any) -> Optional[str]:
    """
    Gibt einen stabilen Reference-Code zurück (z. B. '12 0 R'), wenn `obj` ein
    pypdf IndirectObject ist. Sonst None.
    """
    try:
        idnum = getattr(obj, "idnum", None)
        generation = getattr(obj, "generation", None)
        if idnum is None or generation is None:
            return None
        return f"{int(idnum)} {int(generation)} R"
    except Exception:
        return None


def _normalize_rect(rect: Any) -> Optional[List[float]]:
    try:
        if rect is None:
            return None
        # rect ist oft ein Array/RectangleObject: [llx, lly, urx, ury]
        vals = list(rect)
        if len(vals) != 4:
            return None
        out: List[float] = []
        for v in vals:
            try:
                out.append(float(v))
            except Exception:
                return None
        return out
    except Exception:
        return None


def _build_field_id(
    *,
    page_index: int,
    widget_ref: Optional[str],
    parent_ref: Optional[str],
    rect: Optional[List[float]],
    field_name_fallback: Optional[str],
) -> str:
    """
    Erzeugt eine stabile field_id als Code/Selector.
    Priorität:
    - Indirect-Refs (widget_ref/parent_ref)
    - Rect+Page
    - Hash aus field_name (kurz) als letzter Fallback
    """
    parts: List[str] = [f"p{page_index}"]
    if widget_ref:
        parts.append("w" + widget_ref.replace(" ", "_"))
    if parent_ref and parent_ref != widget_ref:
        parts.append("f" + parent_ref.replace(" ", "_"))
    if rect:
        # bewusst nur als Fallback-Entropie; rect kann auch bei manchen PDFs fehlen
        parts.append("r" + ",".join(f"{v:.2f}" for v in rect))

    # Wenn wir wenigstens Ref oder Rect haben, reicht das als Selector.
    if len(parts) > 1:
        return "|".join(parts)

    # Letzter Fallback: kurzer Hash (kein Klartext-Name in der field_id)
    seed = (field_name_fallback or "") + f"|{page_index}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]  # kurz & stabil
    return f"p{page_index}|h{digest}"


def extract_pdf_acroform_descriptors(reader: Any) -> List[PdfFieldDescriptor]:
    """
    Extrahiert Widget-Felder (AcroForm) inkl. stabiler field_id aus einem PdfReader.
    """
    descriptors: List[PdfFieldDescriptor] = []
    try:
        pages = list(getattr(reader, "pages", []) or [])
    except Exception:
        pages = []

    for page_index, page in enumerate(pages):
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if not annots:
            continue

        for annot_ref in annots:
            widget_ref_code = _pdf_indirect_ref_code(annot_ref)
            try:
                annot = annot_ref.get_object()
            except Exception:
                continue

            try:
                if annot.get("/Subtype") != "/Widget":
                    continue
            except Exception:
                continue

            # Parent-Objekt bestimmen (ähnlich wie beim Filler)
            parent_ref_obj = None
            parent_ref_code = None
            parent = None
            try:
                if "/FT" in annot and "/T" in annot:
                    parent = annot
                else:
                    parent_ref_obj = annot.get("/Parent")
                    parent_ref_code = _pdf_indirect_ref_code(parent_ref_obj)
                    try:
                        parent = parent_ref_obj.get_object() if parent_ref_obj else annot
                    except Exception:
                        parent = annot
            except Exception:
                parent = annot

            # Feldname
            field_name = None
            try:
                t = (parent.get("/T") if parent else None) or annot.get("/T")
                field_name = str(t) if t is not None else None
            except Exception:
                field_name = None

            if not field_name:
                continue

            # Label/Hint
            label_hint = None
            try:
                label_hint = (parent.get("/TU") if parent else None) or annot.get("/TU")
            except Exception:
                label_hint = None
            label_hint_str = str(label_hint) if label_hint is not None else field_name

            # Feldtyp
            ft = None
            try:
                ft = (parent.get("/FT") if parent else None) or annot.get("/FT")
            except Exception:
                ft = None
            ft_str = str(ft) if ft is not None else None

            rect = None
            try:
                rect = _normalize_rect(annot.get("/Rect"))
            except Exception:
                rect = None

            field_id = _build_field_id(
                page_index=page_index,
                widget_ref=widget_ref_code,
                parent_ref=parent_ref_code,
                rect=rect,
                field_name_fallback=field_name,
            )

            descriptors.append(
                PdfFieldDescriptor(
                    field_id=field_id,
                    field_name=field_name,
                    label_hint=label_hint_str,
                    field_type=ft_str,
                    page_index=page_index,
                    rect=rect,
                    widget_ref=widget_ref_code,
                    parent_ref=parent_ref_code,
                )
            )

    return descriptors


def _safe_getattr(obj: Any, key: str) -> Any:
    """
    Hilfsfunktion, um verschachtelte Keys wie "first_name" oder "address.city" zu lesen.
    """
    parts = key.split(".")
    current = obj
    for part in parts:
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def build_fallback_mapping_for_customer(
    field_names: List[str], customer: CustomerProfile
) -> List[MappingEntry]:
    """
    Einfache Fallback-Mapping-Strategie:
    - Direktes Matching auf CustomerProfile-Felder
    - Ein paar Hand-Mappings (z. B. 'vorname' -> first_name)
    """
    customer_dict = model_to_dict(customer)
    synonym_map = {
        "vorname": "first_name",
        "nachname": "last_name",
        "name": "last_name",
        "telefon": "phone",
        "telefonnummer": "phone",
        "plz": "postal_code",
        "stadt": "city",
        "ort": "city",
        "email": "email",
        "e-mail": "email",
        "e_mail": "email",
        "beschäftigungsstatus": "employment_status",
        "einkommen": "monthly_income",
    }

    mappings: List[MappingEntry] = []
    for raw_name in field_names:
        key = raw_name.strip()
        key_lower = key.lower()

        customer_key: Optional[str] = None
        if key in customer_dict:
            customer_key = key
        elif key_lower in customer_dict:
            customer_key = key_lower
        elif key_lower in synonym_map and synonym_map[key_lower] in customer_dict:
            customer_key = synonym_map[key_lower]

        if customer_key:
            value = customer_dict.get(customer_key)
            if value is None:
                mappings.append(
                    MappingEntry(
                        template_field=key,
                        customer_key=customer_key,
                        value=None,
                        confidence=0.9,
                        status="missing",
                        field_id=None,
                    )
                )
            else:
                mappings.append(
                    MappingEntry(
                        template_field=key,
                        customer_key=customer_key,
                        value=str(value),
                        confidence=0.9,
                        status="filled",
                        field_id=None,
                    )
                )
        else:
            mappings.append(
                MappingEntry(
                    template_field=key,
                    customer_key=None,
                    value=None,
                    confidence=0.0,
                    status="missing",
                    field_id=None,
                )
            )

    return mappings


def _get_openai_client():
    """
    Optionaler OpenAI-Client basierend auf OPENAI_KEY/OPENAI_API_KEY.
    Gibt None zurück, wenn OpenAI nicht konfiguriert ist.
    """
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None

    api_key = (
        getattr(settings, "OPENAI_API_KEY", None)
        or getattr(settings, "OPENAI_KEY", None)
        or settings.CONFIG.get("OPENAI_KEY")  # type: ignore[attr-defined]
        if hasattr(settings, "CONFIG")
        else None
    )
    if not api_key:
        # Fallback direkt aus ENV
        import os

        api_key = os.environ.get("OPENAI_KEY") or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return None

    return OpenAI(api_key=api_key)


def _autofill_llm_enabled() -> bool:
    """
    Feature-Flag, um LLM-Mapping deterministisch ein-/auszuschalten.
    - Default: enabled
    - Override: AUTOFILL_LLM_ENABLED=true/false
    """
    env_val = os.environ.get("AUTOFILL_LLM_ENABLED")
    if env_val is None or env_val == "":
        return True
    return env_val.lower() in ("1", "true", "yes", "y", "on")


def _openai_autofill_model_name() -> str:
    return os.environ.get("OPENAI_MODEL_AUTOFILL") or "gpt-5.2"


def build_customer_payload(customer: CustomerProfile) -> Dict[str, Any]:
    """
    Datensparsame, JSON-serialisierbare Customer-Payload für das LLM.
    """
    customer_dict = model_to_dict(customer)
    allowed_keys = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "street",
        "postal_code",
        "city",
        "employment_status",
        "monthly_income",
    ]

    out: Dict[str, Any] = {}
    for k in allowed_keys:
        if k not in customer_dict:
            continue
        v = customer_dict.get(k)
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            if isinstance(v, str) and v.strip() == "":
                continue
            out[k] = v
        else:
            # Decimal/Date/etc. stabil als String
            out[k] = str(v)
    return out


def _looks_like_indirect_ref(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    parts = s.split()
    return len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2] == "R"


def _extract_widget_ref_from_field_ref(field_ref: str) -> Optional[str]:
    """
    Unterstützt:
    - '12 0 R'
    - 'p0|w12_0_R|f...' (unser alter Stil) -> extrahiert '12 0 R'
    """
    fr = (field_ref or "").strip()
    if _looks_like_indirect_ref(fr):
        return fr
    # alter Stil: '...|w12_0_R|...'
    if "|w" in fr and "_R" in fr:
        try:
            # naive Extraktion: find segment starting with w and ending with _R
            segs = fr.split("|")
            for seg in segs:
                seg = seg.strip()
                if seg.startswith("w") and seg.endswith("_R"):
                    code = seg[1:].replace("_", " ")
                    if _looks_like_indirect_ref(code):
                        return code
        except Exception:
            return None
    return None


def _build_widget_ref_to_field_name(reader: Any) -> Dict[str, str]:
    """
    Baut ein Lookup: Widget-IndirectRef ('12 0 R') -> Feldname (/T oder best-effort).
    Das ist KEIN semantisches Mapping, sondern nur Auflösung einer Referenz auf ein echtes Feld.
    """
    out: Dict[str, str] = {}
    try:
        pages = list(getattr(reader, "pages", []) or [])
    except Exception:
        pages = []

    for page in pages:
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if not annots:
            continue

        for annot_ref in annots:
            ref_code = _pdf_indirect_ref_code(annot_ref)
            if not ref_code or ref_code in out:
                continue
            try:
                annot = annot_ref.get_object()
            except Exception:
                continue
            try:
                if annot.get("/Subtype") != "/Widget":
                    continue
            except Exception:
                continue

            # Parent-Objekt bestimmen (ähnlich wie beim Filler)
            try:
                if "/FT" in annot and "/T" in annot:
                    parent = annot
                else:
                    parent_ref = annot.get("/Parent")
                    try:
                        parent = parent_ref.get_object() if parent_ref else annot
                    except Exception:
                        parent = annot
            except Exception:
                parent = annot

            # Feldname best-effort
            field_name = None
            try:
                t = (parent.get("/T") if parent else None) or annot.get("/T")
                field_name = str(t) if t is not None else None
            except Exception:
                field_name = None
            if field_name:
                out[ref_code] = field_name

    return out


def _normalize_match_key(s: str) -> str:
    """
    Normalisierung für deterministisches Matching (keine Semantik):
    - lower
    - entfernt alles außer [a-z0-9]
    """
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _build_label_index_from_fields(fields: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Index: normalisiertes Label (/TU oder /T) -> Liste von echten Feldnamen (/T-Keys).
    """
    index: Dict[str, List[str]] = {}
    for field_name, field in (fields or {}).items():
        if not field_name:
            continue
        try:
            label = field.get("/TU") or field.get("/T") or field_name
        except Exception:
            label = field_name
        norm = _normalize_match_key(str(label))
        if not norm:
            continue
        index.setdefault(norm, []).append(field_name)

        # Zusätzlich: letzten Segment-Token indexieren (z.B. "...Telefon[0]" -> "telefon")
        try:
            last = str(field_name).split(".")[-1]
            last_norm = _normalize_match_key(last)
            if last_norm:
                index.setdefault(last_norm, []).append(field_name)
        except Exception:
            pass
    return index


def _resolve_field_ref_to_field_name(
    field_ref: str, *, field_names: List[str], fields: Dict[str, Any]
) -> Optional[str]:
    """
    Deterministische Auflösung von field_ref auf einen echten /T Feldnamen.
    Unterstützt:
    - exakter /T Name
    - exaktes /TU Label
    - /TU Label mit Suffix _2/_3/... (nth occurrence)
    """
    fr = (field_ref or "").strip()
    if not fr:
        return None

    # Direkter Treffer (exakter /T)
    if fr in set(field_names or []):
        return fr

    # Suffix _N (1-based)
    base = fr
    nth: Optional[int] = None
    m = re.match(r"^(.*)_([0-9]+)$", fr)
    if m:
        base = m.group(1).strip()
        try:
            nth = int(m.group(2))
        except Exception:
            nth = None

    index = _build_label_index_from_fields(fields)
    candidates = index.get(_normalize_match_key(base)) or []
    if not candidates:
        return None

    # Stabil sortieren, damit _2/_3 konsistent ist
    candidates = sorted(set(candidates))
    if nth and 1 <= nth <= len(candidates):
        return candidates[nth - 1]
    return candidates[0]


def _extract_openai_text(response: Any) -> str:
    """
    Best-effort Extraktion aus verschiedenen OpenAI SDK Response-Formaten.
    """
    try:
        txt = getattr(response, "output_text", None)
        if isinstance(txt, str) and txt.strip():
            return txt
    except Exception:
        pass

    # Responses API: response.output[*].content[*].text
    try:
        out_parts: List[str] = []
        for item in (getattr(response, "output", None) or []) or []:
            for c in (getattr(item, "content", None) or []) or []:
                t = getattr(c, "text", None)
                if isinstance(t, str) and t.strip():
                    out_parts.append(t)
        if out_parts:
            return "\n".join(out_parts)
    except Exception:
        pass

    # Chat Completions: response.choices[0].message.content
    try:
        choices = getattr(response, "choices", None) or []
        if choices:
            msg = getattr(choices[0], "message", None)
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                return content
    except Exception:
        pass

    return ""


def build_llm_mapping_for_customer(
    pdf_bytes: bytes,
    customer_payload: Dict[str, Any],
    customer_keys: List[str],
) -> Optional[List[MappingEntry]]:
    """
    Variante B:
    Die KI bekommt NUR das PDF (keine lokal extrahierten Feld-Listen) und liefert ein Mapping
    in der Form {field_ref, customer_key} zurück.

    field_ref bevorzugt:
    - AcroForm Feldname (/T) exakt wie im PDF
    - falls nicht möglich: Widget-IndirectRef '12 0 R'

    Falls etwas schiefgeht, wird None zurückgegeben und der Caller kann auf Fallback gehen.
    """
    if not _autofill_llm_enabled():
        return None

    client = _get_openai_client()
    if client is None or not pdf_bytes or not customer_keys:
        return None

    system_prompt = (
        "Du bist ein Assistent, der ein PDF analysiert und alle ausfüllbaren PDF-AcroForm-Felder "
        "findet und diese Felder auf Customer-Keys mappt. Antworte ausschliesslich mit JSON.\n\n"
        "WICHTIG:\n"
        "- Du bekommst ein PDF.\n"
        "- Finde ALLE ausfüllbaren AcroForm-Widget-Felder, inkl. Feldtypen:\n"
        "  - Text (/Tx)\n"
        "  - Buttons (/Btn): Checkbox/Radio\n"
        "  - Choice (/Ch): Dropdown/List\n"
        "- Setze für jedes gefundene Feld eine `field_ref`.\n"
        "- `field_ref` soll bevorzugt der EXAKTE AcroForm-Feldname aus dem PDF sein, also der Wert von /T.\n"
        "  Das ist oft ein vollständig qualifizierter Pfad mit Indizes, z.B.:\n"
        "  - form1[0].V1[0].Telefon[0]\n"
        "  - form1[0].V1[0].EMail[0]\n"
        "  - form1[0].V1[0].Ort_Strasse_HausNr[0]\n"
        "- Wenn du /T nicht zuverlässig extrahieren kannst, nutze als field_ref ersatzweise das /TU (Tooltip/Label) EXAKT wie im PDF.\n"
        "- Wenn du keinen /T Feldnamen zuverlässig extrahieren kannst, nutze ersatzweise die Widget-IndirectRef im Format '12 0 R'.\n"
        "- Achte bei /Btn Feldern darauf, dass du das konkrete Feld (seinen /T Namen) mapst (nicht das sichtbare Label).\n"
        "- Achte bei /Ch Feldern darauf, dass du das Dropdown/List-Feld (/T) mapst.\n"
        "- Deine Ausgabe darf KEINE Erklärtexte enthalten; gib nur JSON mit `field_ref` aus.\n"
        "- Setze `customer_key` nur dann auf null, wenn wirklich KEIN sinnvolles Feld existiert.\n"
        "- Erfinde KEINE Daten. Wenn `customer_key` null ist, bleibt das Feld leer."
    )

    try:
        model_name = _openai_autofill_model_name()
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        pdf_file_data = f"data:application/pdf;base64,{pdf_b64}"

        # Für Variante B ist File-Input Pflicht (sonst kann die KI das PDF nicht analysieren).
        if not (hasattr(client, "responses") and hasattr(client.responses, "create")):
            _autofill_print(
                "[LLM] Responses API nicht verfügbar – kann PDF nicht an KI senden, nutze Fallback",
                {"model": model_name},
            )
            return None

        user_text = (
            "Du erhältst eine PDF-Datei.\n"
            "Erzeuge ein Mapping NUR für Felder, die zu den gegebenen customer_keys passen.\n"
            "Ignoriere alle anderen Felder.\n\n"
            "Erlaubte customer_keys:\n"
            + json.dumps({"customer_keys": customer_keys, "customer": customer_payload}, ensure_ascii=False, default=str)
            + "\n\n"
            "Antworte als JSON-Objekt exakt in dieser Form:\n"
            "{\"mappings\": [{\"field_ref\": str, \"customer_key\": str|null, \"confidence\": float}]}\n\n"
            "WICHTIG:\n"
            "- `field_ref` muss exakt dem /T-Feldnamen aus dem PDF entsprechen (z.B. 'form1[0].V1[0].Telefon[0]').\n"
            "- Wenn du /T nicht extrahieren kannst, nutze /TU (Tooltip/Label) exakt wie im PDF als field_ref.\n"
            "- Gib maximal 30 mappings zurück.\n"
            "- Gib keine Erklärtexte aus, nur JSON."
        )

        try:
            resp = client.responses.create(
                model=model_name,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                {
                    "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": "document.pdf",
                                "file_data": pdf_file_data,
                            },
                            {"type": "input_text", "text": user_text},
                        ],
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except TypeError:
            resp = client.responses.create(
                model=model_name,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": "document.pdf",
                                "file_data": pdf_file_data,
                            },
                            {"type": "input_text", "text": user_text},
                        ],
                },
            ],
            temperature=0.0,
        )

        content = _extract_openai_text(resp) or "{}"

        data = json.loads(content or "{}")
        mappings_raw = data.get("mappings", [])
    except Exception:
        return None

    # Debug-Logging: zeigt das vom LLM vorgeschlagene Mapping
    try:
        # Raw-Mappings sind extrem groß → nur im Verbose-Debug ausgeben
        _autofill_print("[LLM][MAPPINGS_RAW]", {"mappings_raw": mappings_raw}, verbose_only=True)
    except Exception:
        pass

    # WICHTIG (User-Wunsch): KEINE weitere Verarbeitung/Reduzierung der KI-Ausgabe.
    # Wir übernehmen die Mappings 1:1 in derselben Reihenfolge, inkl. Duplikaten.
    out: List[MappingEntry] = []
    for m in mappings_raw or []:
        field_ref = str(m.get("field_ref", "")).strip()
        if not field_ref:
            continue
        ck = m.get("customer_key")
        ck = str(ck).strip() if ck is not None else None
        try:
            conf = float(m.get("confidence", 0.0))
        except Exception:
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        out.append(
            MappingEntry(
                template_field=field_ref,
                customer_key=ck,
                value=None,
                confidence=conf,
                status="missing",
                field_id=field_ref,
            )
        )
    return out


def build_mapping_for_customer(
    field_names: List[str],
    customer: CustomerProfile,
    *,
    pdf_bytes: bytes,
    reader: Any,
) -> List[MappingEntry]:
    """
    Bevorzugt LLM-Mapping, fällt bei Fehlern oder fehlender Konfiguration
    automatisch auf die Fallback-Heuristik zurück.
    """
    strategy, mappings = build_mapping_for_customer_with_strategy(
        field_names, customer, pdf_bytes=pdf_bytes, reader=reader
    )

    if strategy == "llm_gpt52":
        filled = sum(
            1 for m in mappings if m.status == "filled" and m.value is not None
        )
        missing = len(mappings) - filled
        _autofill_print(
            "LLM mapping used",
            {
                "customer_id": customer.pk,
                "form_fields": len(field_names),
                "mappings": len(mappings),
                "filled": filled,
                "missing": missing,
                "filled_sample": [
                    {
                        "field_ref": m.field_id,
                        "field": m.template_field,
                        "customer_key": m.customer_key,
                        "value": m.value,
                    }
                    for m in mappings
                    if m.status == "filled" and m.value is not None
                ][:10],
            },
        )
    else:
        _autofill_print(
            "Fallback mapping used",
            {"customer_id": customer.pk, "form_fields": len(field_names)},
        )

    return mappings


def build_mapping_for_customer_with_strategy(
    field_names: List[str],
    customer: CustomerProfile,
    *,
    pdf_bytes: bytes,
    reader: Any,
) -> Tuple[str, List[MappingEntry]]:
    """
    Wie `build_mapping_for_customer`, aber gibt zusätzlich die Strategy zurück:
    - 'llm_gpt52' oder 'fallback_mapping'
    """
    # Erlaubte Keys: bewusst das stabile Schema (nicht nur non-empty values),
    # damit die KI auch Felder mappen kann, deren Wert beim Kunden gerade leer ist.
    allowed_customer_keys = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "street",
        "postal_code",
        "city",
        "employment_status",
        "monthly_income",
    ]

    llm_raw = build_llm_mapping_for_customer(
        pdf_bytes,
        build_customer_payload(customer),
        allowed_customer_keys,
    )
    if llm_raw is not None and llm_raw:
        # WICHTIG (User-Wunsch): KEINE lokale Auflösung/Verarbeitung der KI-Ausgabe.
        # Wir verwenden field_ref direkt als Feldname (muss /T sein, sonst wird es nicht matchen).
        resolved: List[MappingEntry] = []
        customer_dict_full = model_to_dict(customer)

        for m in llm_raw:
            field_ref = (m.field_id or m.template_field or "").strip()
            ck = m.customer_key
            value = None
            status = "missing"
            if field_ref and ck and ck in customer_dict_full:
                raw_val = customer_dict_full.get(ck)
                if raw_val is not None and str(raw_val).strip() != "":
                    value = str(raw_val)
                    status = "filled"

            resolved.append(
                MappingEntry(
                    template_field=field_ref,
                    customer_key=ck,
                    value=value,
                    confidence=m.confidence,
                    status=status,
                    field_id=field_ref,  # field_ref im Report
                )
            )

        return "llm_gpt52", resolved

    # Fallback über Feldnamen (kompatibel zum bestehenden PDF-Filler)
    fallback = build_fallback_mapping_for_customer(field_names, customer)
    for f in fallback:
        # field_ref als Feldname im Report
        f.field_id = f.template_field
    return "fallback_mapping", fallback


def _build_value_dict_from_mappings(
    mappings: List[MappingEntry],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Erzeugt value_dict (field_name -> value) inkl. Konflikt-Erkennung, falls
    mehrere MappingEntries denselben field_name mit unterschiedlichen Werten liefern.
    """
    best: Dict[str, MappingEntry] = {}
    conflicts: List[Dict[str, Any]] = []

    for m in mappings:
        if not (m.status == "filled" and m.value is not None):
            continue
        key = (m.template_field or "").strip()
        if not key:
            continue

        prev = best.get(key)
        if prev is None:
            best[key] = m
            continue

        if prev.value == m.value:
            # identisch → egal
            if m.confidence > prev.confidence:
                best[key] = m
            continue

        # Konflikt: zwei verschiedene Werte für dasselbe Feld
        keep = prev
        drop = m
        if m.confidence > prev.confidence:
            keep, drop = m, prev
            best[key] = m

        conflicts.append(
            {
                "field_name": key,
                "kept": {
                    "field_ref": keep.field_id,
                    "customer_key": keep.customer_key,
                    "value": keep.value,
                    "confidence": keep.confidence,
                },
                "dropped": {
                    "field_ref": drop.field_id,
                    "customer_key": drop.customer_key,
                    "value": drop.value,
                    "confidence": drop.confidence,
                },
            }
        )

    value_dict: Dict[str, Any] = {k: v.value for k, v in best.items() if v.value is not None}
    return value_dict, conflicts


def update_field_schema_for_template(template: DocumentTemplate) -> None:
    """
    Field-Schema-Parser (MVP):
    - Für PDF-AcroForm Templates: liest Formularfelder über pypdf ein.
    - Für DOCX Templates: belässt field_schema leer (Context-basiertes Rendering).
    """
    if template.type == DocumentTemplate.Type.PDF_ACROFORM and PdfReader is not None:
        file = template.file
        if not file:
            return

        file.open("rb")
        try:
            pdf_bytes = file.read()
        finally:
            file.close()

        reader = PdfReader(BytesIO(pdf_bytes))
        fields = reader.get_fields() or {}

        schema: List[Dict[str, Any]] = []
        for name, field in fields.items():
            if not name:
                continue
            label = field.get("/TU") or field.get("/T") or name
            schema.append({"name": name, "label": label, "type": "text"})

        template.field_schema = schema
        template.save(update_fields=["field_schema"])


def _render_docx_template(
    template: DocumentTemplate,
    customer: CustomerProfile,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    DOCX Renderer:
    - Verwendet docxtpl und stellt den Customer als Dictionary im Kontext bereit.
    - Mapping-Report ist hier generisch, da Feldschema nicht ausgelesen wird.
    """
    if DocxTemplate is None:
        raise RuntimeError("docxtpl ist nicht installiert, DOCX-Autofill nicht möglich.")

    if not template.file:
        raise ValueError("Template hat keine Datei.")

    doc = DocxTemplate(template.file.path)
    context = {
        "customer": model_to_dict(customer),
    }
    doc.render(context)

    buf = BytesIO()
    doc.save(buf)

    mapping_report = {
        "strategy": "context_customer_full",
        "note": "DOCX-Template wurde mit vollständigem Customer-Kontext gerendert.",
        "customer_keys": list(context["customer"].keys()),
    }
    return buf.getvalue(), mapping_report


def _render_pdf_acroform_template(
    template: DocumentTemplate,
    customer: CustomerProfile,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    PDF-AcroForm Renderer:
    - Liest Feldnamen aus dem Template (field_schema oder pypdf),
    - erstellt ein Fallback-Mapping und füllt die Formularfelder.
    """
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("pypdf ist nicht installiert, PDF-Autofill nicht möglich.")

    if not template.file:
        raise ValueError("Template hat keine Datei.")

    # PDF Bytes einmalig lesen (wird für Reader+LLM benötigt)
    file = template.file
    file.open("rb")
    try:
        pdf_bytes = file.read()
    finally:
        file.close()

    reader = PdfReader(BytesIO(pdf_bytes))
    fields = reader.get_fields() or {}
    field_names = [name for name in fields.keys() if name]

    _autofill_print(
        "PDF template fields extracted",
        {
            "template_id": template.pk,
            "field_count": len(field_names),
            "field_sample": field_names[:10],
        },
    )

    if not field_names:
        mapping_report = {
            "strategy": "no_acroform",
            "note": "PDF enthält keine Formularfelder; Datei wurde unverändert übernommen.",
        }
        return pdf_bytes, mapping_report

    strategy, mappings = build_mapping_for_customer_with_strategy(
        field_names, customer, pdf_bytes=pdf_bytes, reader=reader
    )

    _autofill_print(
        "PDF template mappings",
        {
            "template_id": template.pk,
            "strategy": strategy,
            "mappings": len(mappings),
            "filled": sum(
                1 for m in mappings if m.status == "filled" and m.value is not None
            ),
            "missing": sum(1 for m in mappings if m.status != "filled" or m.value is None),
        },
    )

    writer = PdfWriter()
    try:
        writer.clone_document_from_reader(reader)
        _autofill_print("PDF clone_document_from_reader ok", {"template_id": template.pk})
    except Exception as exc:
        _autofill_print(
            "PDF clone_document_from_reader failed (fallback add_page)",
            {"template_id": template.pk, "error": str(exc)},
        )
        for page in reader.pages:
            writer.add_page(page)

    # WICHTIG (User-Wunsch): raw mappings ohne Reduktion anwenden.
    fill_targets = [m for m in mappings if m.status == "filled" and m.value is not None]
    _autofill_print(
        "PDF template fill_targets",
        {
            "template_id": template.pk,
            "fill_targets": len(fill_targets),
            "fill_sample": [
                {"field_ref": m.template_field, "value": m.value, "customer_key": m.customer_key}
                for m in fill_targets[:10]
            ],
        },
    )

    fill_error: Optional[str] = None
    any_success = False
    if writer.pages and fill_targets:
        # In derselben Reihenfolge wie von der KI geliefert anwenden (Duplikate inklusive).
        errors: List[str] = []
        for m in fill_targets:
            err = _safe_fill_pdf_form_fields(writer, {m.template_field: m.value})
            if err is None:
                any_success = True
            else:
                if len(errors) < 5:
                    errors.append(err)
        if not any_success:
            fill_error = errors[0] if errors else "Keine Felder wurden aktualisiert."

        out_buf = BytesIO()
        writer.write(out_buf)

    mapping_report: Dict[str, Any] = {
        "strategy": strategy,
        "fields": [
            {
                "field_ref": m.field_id,
                "field_name": m.template_field,
                "customer_key": m.customer_key,
                "confidence": m.confidence,
                "value": m.value,
                "status": m.status,
            }
            for m in mappings
        ],
    }
    if fill_error:
        mapping_report["fill_error"] = fill_error
    return out_buf.getvalue(), mapping_report


def run_autofill_for_customer(
    template: DocumentTemplate,
    customer: CustomerProfile,
    existing_document: Optional[CustomerDocument] = None,
) -> CustomerDocument:
    """
    Kernfunktion für Flow C:
    1) Template-Typ prüfen
    2) Dokument generieren (DOCX oder PDF AcroForm)
    3) CustomerDocument anlegen und Mapping-Report speichern
    """
    if template.type == DocumentTemplate.Type.DOCX:
        content, mapping_report = _render_docx_template(template, customer)
        ext = "docx"
    elif template.type == DocumentTemplate.Type.PDF_ACROFORM:
        content, mapping_report = _render_pdf_acroform_template(template, customer)
        ext = "pdf"
    else:
        raise ValueError(f"Unsupported template type: {template.type}")

    filename = f"customer_{customer.pk}_template_{template.pk}.{ext}"

    if existing_document is None:
        doc = CustomerDocument(
            broker=customer.broker,
            customer=customer,
            template=template,
            status=CustomerDocument.Status.DRAFT,
            mapping_report=mapping_report,
        )
    else:
        doc = existing_document
        doc.broker = customer.broker
        doc.customer = customer
        doc.template = template
        doc.status = CustomerDocument.Status.DRAFT
        doc.mapping_report = mapping_report

    doc.generated_file.save(filename, ContentFile(content), save=True)
    return doc


def run_autofill_for_document(
    document: CustomerDocument,
    customer: CustomerProfile,
) -> CustomerDocument:
    """
    Autofill für ein bestehendes Kundendokument:
    - Verwendet die Datei des Dokuments (generated_file oder uploaded_file) als Basis,
    - unterstützt DOCX (docxtpl) und PDF AcroForm (pypdf),
    - überschreibt generated_file und Mapping-Report des Dokuments.
    """
    file_field = document.generated_file or document.uploaded_file
    if not file_field:
        raise ValueError("Für dieses Kundendokument ist keine Datei hinterlegt.")

    name = (file_field.name or "").lower()
    _autofill_print(
        "run_autofill_for_document start",
        {
            "document_id": document.pk,
            "customer_id": customer.pk,
            "file_name": file_field.name,
            "file_ext": name.rsplit(".", 1)[-1] if "." in name else "",
        },
    )

    if name.endswith(".docx"):
        if DocxTemplate is None:
            raise RuntimeError(
                "docxtpl ist nicht installiert, DOCX-Autofill für Kundendokumente nicht möglich."
            )
        tpl = DocxTemplate(file_field.path)
        context = {"customer": model_to_dict(customer)}
        tpl.render(context)
        buf = BytesIO()
        tpl.save(buf)
        content = buf.getvalue()
        mapping_report = {
            "strategy": "context_customer_full",
            "note": "DOCX-Kundendokument wurde mit vollständigem Customer-Kontext gerendert.",
            "customer_keys": list(context["customer"].keys()),
        }
        ext = "docx"
    elif name.endswith(".pdf"):
        if PdfReader is None or PdfWriter is None:
            raise RuntimeError(
                "pypdf ist nicht installiert, PDF-Autofill für Kundendokumente nicht möglich."
            )

        file_field.open("rb")
        try:
            pdf_bytes = file_field.read()
        finally:
            file_field.close()

        reader = PdfReader(BytesIO(pdf_bytes))
        fields = reader.get_fields() or {}
        field_names = [fname for fname in fields.keys() if fname]
        _autofill_print(
            "PDF document fields extracted",
            {
                "document_id": document.pk,
                "field_count": len(field_names),
                "field_sample": field_names[:10],
            },
        )

        writer = PdfWriter()
        # Wichtig: Dokument inkl. AcroForm korrekt klonen (sonst fehlen nach writer.write
        # oft /AcroForm, /Fields oder referenzierte Objekte).
        try:
            writer.clone_document_from_reader(reader)
            _autofill_print("PDF clone_document_from_reader ok", {"document_id": document.pk})
        except Exception:
            _autofill_print(
                "PDF clone_document_from_reader failed (fallback add_page)",
                {"document_id": document.pk},
            )
            for page in reader.pages:
                writer.add_page(page)

        fill_error: Optional[str] = None

        if field_names:
            strategy, mappings = build_mapping_for_customer_with_strategy(
                field_names, customer, pdf_bytes=pdf_bytes, reader=reader
            )
            _autofill_print(
                "PDF document mappings",
                {
                    "document_id": document.pk,
                    "strategy": strategy,
                    "mappings": len(mappings),
                    "filled": sum(
                        1
                        for m in mappings
                        if m.status == "filled" and m.value is not None
                    ),
                    "missing": sum(
                        1 for m in mappings if m.status != "filled" or m.value is None
                    ),
                },
            )

            fill_targets = [m for m in mappings if m.status == "filled" and m.value is not None]
            _autofill_print(
                "PDF document fill_targets",
                {
                    "document_id": document.pk,
                    "fill_targets": len(fill_targets),
                    "fill_sample": [
                        {"field_ref": m.template_field, "value": m.value, "customer_key": m.customer_key}
                        for m in fill_targets[:10]
                    ],
                },
            )

            any_success = False
            if writer.pages and fill_targets:
                errors: List[str] = []
                for m in fill_targets:
                    err = _safe_fill_pdf_form_fields(writer, {m.template_field: m.value})
                    if err is None:
                        any_success = True
                    else:
                        if len(errors) < 5:
                            errors.append(err)
                if not any_success:
                    fill_error = errors[0] if errors else "Keine Felder wurden aktualisiert."

            if fill_error:
                _autofill_print(
                    "PDF document fill_error",
                    {"document_id": document.pk, "error": fill_error},
                )

            mapping_report = {
                "strategy": strategy,
                "fields": [
                    {
                        "field_ref": m.field_id,
                        "field_name": m.template_field,
                        "customer_key": m.customer_key,
                        "confidence": m.confidence,
                        "value": m.value,
                        "status": m.status,
                    }
                    for m in mappings
                ],
            }
            if fill_error:
                mapping_report["fill_error"] = fill_error
        else:
            mapping_report = {
                "strategy": "no_acroform",
                "note": "PDF enthält keine Formularfelder; Datei wurde unverändert übernommen.",
            }

        out_buf = BytesIO()
        writer.write(out_buf)
        content = out_buf.getvalue()
        ext = "pdf"
    else:
        raise ValueError(
            f"Nicht unterstütztes Dokumentformat für Autofill: {file_field.name}"
        )

    filename = f"customer_{customer.pk}_document_{document.pk}.{ext}"
    document.status = CustomerDocument.Status.DRAFT
    document.mapping_report = mapping_report
    document.generated_file.save(filename, ContentFile(content), save=True)
    return document


