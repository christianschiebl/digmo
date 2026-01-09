from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from django.core.files.base import ContentFile
from django.forms.models import model_to_dict

from customers.models import CustomerProfile
from .models import CustomerDocument, DocumentTemplate
from .openai_code_interpreter import build_pdf_field_mapping

try:
    from docxtpl import DocxTemplate  # type: ignore
except Exception as e:  # pragma: no cover
    DocxTemplate = None  # type: ignore
    _DOCX_IMPORT_ERROR = e
else:
    _DOCX_IMPORT_ERROR = None

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    from pypdf.generic import (  # type: ignore
        BooleanObject,
        IndirectObject,
        NameObject,
        TextStringObject,
    )
except Exception as e:  # pragma: no cover
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore
    NameObject = None  # type: ignore
    BooleanObject = None  # type: ignore
    TextStringObject = None  # type: ignore
    IndirectObject = None  # type: ignore
    _PDF_IMPORT_ERROR = e
else:
    _PDF_IMPORT_ERROR = None


logger = logging.getLogger(__name__)


# Wir mappen bewusst nur ein stabiles, datensparsames Subset.
ALLOWED_CUSTOMER_KEYS: List[str] = [
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


@dataclass(frozen=True)
class MappingItem:
    field_name: str
    field_object_ref: Optional[str]
    field_type: Optional[str]
    customer_key: Optional[str]
    confidence: float


def _openai_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY fehlt. PDF-Autofill benötigt einen OpenAI API Key.")
    return api_key


def build_customer_payload(customer: CustomerProfile) -> Dict[str, Any]:
    customer_dict = model_to_dict(customer)
    out: Dict[str, Any] = {}
    for k in ALLOWED_CUSTOMER_KEYS:
        if k not in customer_dict:
            continue
        v = customer_dict.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        # Decimal/Date/etc. stabil als String
        out[k] = v if isinstance(v, (str, int, float, bool)) else str(v)
    return out


def _safe_fill_pdf_form_fields(writer: Any, value_dict: Dict[str, Any]) -> Optional[str]:
    """
    Robust: setzt Werte direkt in Field-Dictionaries ("/V") und setzt NeedAppearances.
    Generiert keine Appearances, um kaputte PDFs nicht zu crashen.

    Returns: None bei Erfolg, sonst Fehlertext.
    """
    if not value_dict:
        return None

    if BooleanObject is None or TextStringObject is None or NameObject is None:
        return "pypdf.generic Objekte nicht verfügbar (BooleanObject/TextStringObject/NameObject)."

    # NeedAppearances setzen (damit Viewer rendert)
    try:
        if hasattr(writer, "set_need_appearances_writer"):
            try:
                writer.set_need_appearances_writer(True)
            except Exception:
                pass
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
    except Exception:
        pages = []

    try:
        updated = 0
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

                # Feldname: qualified name falls vorhanden, sonst /T
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
                try:
                    ft = parent.get("/FT") or annot.get("/FT")
                except Exception:
                    ft = None
                ft_str = str(ft) if ft is not None else ""

                def _boolish(v: Any) -> Optional[bool]:
                    if isinstance(v, bool):
                        return v
                    s = str(v).strip().lower()
                    if s in ("1", "true", "yes", "y", "ja", "on", "checked", "x"):
                        return True
                    if s in ("0", "false", "no", "n", "nein", "off", "unchecked", ""):
                        return False
                    return None

                def _pick_on_state(a: Any) -> str:
                    try:
                        ap = a.get("/AP")
                        n = ap.get("/N") if ap else None
                        if n:
                            keys = list(getattr(n, "keys", lambda: [])())
                            for k in keys:
                                ks = str(k)
                                if ks != "/Off":
                                    return ks
                    except Exception:
                        pass
                    return "/Yes"

                def _choice_options(p: Any) -> List[str]:
                    try:
                        opt = p.get("/Opt")
                        if not opt:
                            return []
                        out: List[str] = []
                        for item in list(opt):
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

                try:
                    if ft_str == "/Btn":
                        b = _boolish(raw_value)
                        if b is None:
                            continue
                        on_state = _pick_on_state(parent)
                        parent[NameObject("/V")] = NameObject(on_state if b else "/Off")
                        parent[NameObject("/AS")] = NameObject(on_state if b else "/Off")
                        updated += 1
                    elif ft_str == "/Ch":
                        # Choice: am stabilsten den String schreiben
                        s = str(raw_value)
                        opts = _choice_options(parent)
                        if opts and s not in opts:
                            # Wenn der Wert nicht in den Options ist, trotzdem setzen (einige PDFs erlauben freie Werte).
                            pass
                        parent[NameObject("/V")] = TextStringObject(s)
                        updated += 1
                    else:
                        # Default: Text
                        parent[NameObject("/V")] = TextStringObject(str(raw_value))
                        updated += 1
                except Exception:
                    continue

        if updated == 0:
            return "Keine passenden Formularfelder gefunden/aktualisiert."
        return None
    except Exception as e:
        return str(e)


def update_field_schema_for_template(template: DocumentTemplate) -> None:
    """
    Field-Schema für PDF-AcroForm Templates (UI/Transparenz).
    """
    if template.type != DocumentTemplate.Type.PDF_ACROFORM:
        return
    if PdfReader is None:
        raise RuntimeError(f"pypdf ist nicht verfügbar: {_PDF_IMPORT_ERROR}")
    if not template.file:
        return

    template.file.open("rb")
    try:
        pdf_bytes = template.file.read()
    finally:
        template.file.close()

    reader = PdfReader(BytesIO(pdf_bytes))
    fields = reader.get_fields() or {}

    schema: List[Dict[str, Any]] = []
    for name, field in fields.items():
        if not name:
            continue
        try:
            label = field.get("/TU") or field.get("/T") or name
        except Exception:
            label = name
        try:
            ft = field.get("/FT")
            fts = str(ft).lstrip("/") if ft is not None else "text"
        except Exception:
            fts = "text"
        schema.append({"name": name, "label": str(label), "type": fts})

    template.field_schema = schema
    template.save(update_fields=["field_schema"])


def _render_docx_template(template: DocumentTemplate, customer: CustomerProfile) -> Tuple[bytes, Dict[str, Any]]:
    if DocxTemplate is None:
        raise RuntimeError(f"docxtpl ist nicht installiert: {_DOCX_IMPORT_ERROR}")
    if not template.file:
        raise ValueError("Template hat keine Datei.")

    doc = DocxTemplate(template.file.path)
    context = {"customer": model_to_dict(customer)}
    doc.render(context)
    buf = BytesIO()
    doc.save(buf)
    mapping_report = {
        "strategy": "context_customer_full",
        "note": "DOCX-Template wurde mit vollständigem Customer-Kontext gerendert.",
        "customer_keys": list(context["customer"].keys()),
    }
    return buf.getvalue(), mapping_report


def _parse_mapping_items(mapping_json: Dict[str, Any]) -> List[MappingItem]:
    raw = mapping_json.get("mappings", [])
    if not isinstance(raw, list):
        raise ValueError("Ungültiges Mapping-Format: `mappings` ist keine Liste.")

    out: List[MappingItem] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        field_name = str(m.get("field_name", "")).strip()
        if not field_name:
            continue
        field_object_ref = m.get("field_object_ref")
        field_object_ref = str(field_object_ref).strip() if field_object_ref else None
        field_type = m.get("field_type")
        field_type = str(field_type).strip() if field_type else None
        customer_key = m.get("customer_key")
        customer_key = str(customer_key).strip() if customer_key else None
        try:
            confidence = float(m.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        out.append(
            MappingItem(
                field_name=field_name,
                field_object_ref=field_object_ref,
                field_type=field_type,
                customer_key=customer_key,
                confidence=confidence,
            )
        )
    return out


def _render_pdf_acroform_bytes(
    *, pdf_bytes: bytes, customer: CustomerProfile
) -> Tuple[bytes, Dict[str, Any]]:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError(f"pypdf ist nicht verfügbar: {_PDF_IMPORT_ERROR}")

    reader = PdfReader(BytesIO(pdf_bytes))
    fields = reader.get_fields() or {}
    field_names = {name for name in fields.keys() if name}

    if not field_names:
        return pdf_bytes, {"strategy": "no_acroform", "note": "PDF enthält keine Formularfelder."}

    customer_payload = build_customer_payload(customer)
    api_key = _openai_api_key()
    mapping_json = build_pdf_field_mapping(
        api_key=api_key,
        pdf_bytes=pdf_bytes,
        customer_payload=customer_payload,
        allowed_customer_keys=ALLOWED_CUSTOMER_KEYS,
    )
    mapping_items = _parse_mapping_items(mapping_json)

    customer_dict_full = model_to_dict(customer)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    mapping_report_fields: List[Dict[str, Any]] = []
    fill_error: Optional[str] = None
    any_success = False

    # In der Reihenfolge des Modells anwenden (inkl. Duplikaten).
    for mi in mapping_items:
        value: Optional[str] = None
        status = "missing"

        if mi.customer_key is None:
            status = "unmapped"
        elif mi.customer_key not in customer_dict_full:
            status = "missing"
        else:
            raw_val = customer_dict_full.get(mi.customer_key)
            if raw_val is None or str(raw_val).strip() == "":
                status = "missing"
            elif mi.field_name not in field_names:
                status = "unknown_field"
            else:
                value = str(raw_val)
                status = "filled"

        if status == "filled" and value is not None:
            err = _safe_fill_pdf_form_fields(writer, {mi.field_name: value})
            if err is None:
                any_success = True
            else:
                fill_error = err

        mapping_report_fields.append(
            {
                "field_name": mi.field_name,
                "field_object_ref": mi.field_object_ref,
                "field_type": mi.field_type,
                "customer_key": mi.customer_key,
                "confidence": mi.confidence,
                "value": value,
                "status": status,
            }
        )

    if not any_success:
        fill_error = fill_error or "Keine Felder wurden aktualisiert."

    out_buf = BytesIO()
    writer.write(out_buf)

    report: Dict[str, Any] = {
        "strategy": "gpt52_code_interpreter",
        "fields": mapping_report_fields,
    }
    if fill_error:
        report["fill_error"] = fill_error

    return out_buf.getvalue(), report


def _render_pdf_acroform_template(
    template: DocumentTemplate, customer: CustomerProfile
) -> Tuple[bytes, Dict[str, Any]]:
    if not template.file:
        raise ValueError("Template hat keine Datei.")
    template.file.open("rb")
    try:
        pdf_bytes = template.file.read()
    finally:
        template.file.close()

    return _render_pdf_acroform_bytes(pdf_bytes=pdf_bytes, customer=customer)


def run_autofill_for_customer(
    template: DocumentTemplate,
    customer: CustomerProfile,
    existing_document: Optional[CustomerDocument] = None,
) -> CustomerDocument:
    """
    Flow C:
    - Template (DOCX oder PDF AcroForm) + CustomerProfile -> generiertes Dokument + mapping_report
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


def run_autofill_for_document(document: CustomerDocument, customer: CustomerProfile) -> CustomerDocument:
    """
    Autofill für bestehendes Kundendokument (DOCX oder PDF).
    - PDF: Mapping via GPT-5.2 Code Interpreter (ohne Heuristik-Fallback).
    - DOCX: Kontext-Rendering (deterministisch).
    """
    file_field = document.generated_file or document.uploaded_file
    if not file_field:
        raise ValueError("Für dieses Kundendokument ist keine Datei hinterlegt.")

    name = (file_field.name or "").lower()
    if name.endswith(".docx"):
        if DocxTemplate is None:
            raise RuntimeError(f"docxtpl ist nicht installiert: {_DOCX_IMPORT_ERROR}")
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
        file_field.open("rb")
        try:
            pdf_bytes = file_field.read()
        finally:
            file_field.close()
        content, mapping_report = _render_pdf_acroform_bytes(pdf_bytes=pdf_bytes, customer=customer)
        ext = "pdf"
    else:
        raise ValueError(f"Nicht unterstütztes Dokumentformat für Autofill: {file_field.name}")

    filename = f"customer_{customer.pk}_document_{document.pk}.{ext}"
    document.status = CustomerDocument.Status.DRAFT
    document.mapping_report = mapping_report
    document.generated_file.save(filename, ContentFile(content), save=True)
    return document


