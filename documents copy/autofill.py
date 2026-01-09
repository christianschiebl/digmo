import json
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
    from pypdf.generic import NameObject  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None
    PdfWriter = None
    NameObject = None


@dataclass
class MappingEntry:
    template_field: str
    customer_key: Optional[str]
    value: Optional[str]
    confidence: float
    status: str  # "filled" oder "missing"


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
                )
            )

    return mappings


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
            reader = PdfReader(file)
            fields = reader.get_fields() or {}
        finally:
            file.close()

        schema: List[Dict[str, Any]] = []
        for name, field in fields.items():
            if not name:
                continue
            label = field.get("/TU") or field.get("/T") or name
            schema.append(
                {
                    "name": name,
                    "label": label,
                    "type": "text",
                }
            )
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

    # Feldschema ermitteln (ggf. vorher geparst)
    if template.field_schema:
        field_names = [f.get("name") for f in template.field_schema or [] if f.get("name")]
    else:
        file = template.file
        file.open("rb")
        try:
            reader = PdfReader(file)
            fields = reader.get_fields() or {}
        finally:
            file.close()
        field_names = [name for name in fields.keys() if name]

    mappings = build_fallback_mapping_for_customer(field_names, customer)

    # PDF ausfüllen
    file = template.file
    file.open("rb")
    try:
        reader = PdfReader(file)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        # Sicherstellen, dass das AcroForm-Objekt in den Writer übernommen wird
        if NameObject is not None:
            try:
                root = reader.trailer.get("/Root", {})
                acroform = root.get("/AcroForm") if root else None
                if acroform is not None:
                    writer._root_object[NameObject("/AcroForm")] = acroform
            except Exception:
                # Falls etwas schiefgeht, lieber ohne Feld-Update weitermachen.
                pass

        value_dict = {
            m.template_field: m.value
            for m in mappings
            if m.value is not None and m.status == "filled"
        }
        if writer.pages and value_dict:
            writer.update_page_form_field_values(writer.pages[0], value_dict)

        out_buf = BytesIO()
        writer.write(out_buf)
    finally:
        file.close()

    mapping_report = {
        "strategy": "fallback_mapping",
        "fields": [m.__dict__ for m in mappings],
    }
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
            reader = PdfReader(file_field)
            fields = reader.get_fields() or {}
            field_names = [fname for fname in fields.keys() if fname]

            mappings = build_fallback_mapping_for_customer(field_names, customer) if field_names else []

            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)

            if field_names:
                # Nur versuchen, Formularfelder zu befüllen, wenn ein AcroForm vorhanden ist.
                if NameObject is not None:
                    try:
                        root = reader.trailer.get("/Root", {})
                        acroform = root.get("/AcroForm") if root else None
                        if acroform is not None:
                            writer._root_object[NameObject("/AcroForm")] = acroform
                    except Exception:
                        pass

                value_dict = {
                    m.template_field: m.value
                    for m in mappings
                    if m.value is not None and m.status == "filled"
                }
                if writer.pages and value_dict:
                    writer.update_page_form_field_values(writer.pages[0], value_dict)

            out_buf = BytesIO()
            writer.write(out_buf)
            content = out_buf.getvalue()
        finally:
            file_field.close()

        if field_names:
            mapping_report = {
                "strategy": "fallback_mapping",
                "fields": [m.__dict__ for m in mappings],
            }
        else:
            mapping_report = {
                "strategy": "no_acroform",
                "note": "PDF enthält keine Formularfelder; Datei wurde unverändert übernommen.",
            }
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


