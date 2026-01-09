import base64
import json
import logging
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAIRequestError(RuntimeError):
    pass


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def create_container(*, api_key: str, memory_limit: str = "4g", name: str = "digifynow-autofill") -> str:
    """
    Erstellt einen Code-Interpreter Container (ephemeral).
    Siehe: POST /v1/containers
    """
    resp = requests.post(
        f"{OPENAI_API_BASE}/containers",
        headers=_headers(api_key),
        json={"name": name, "memory_limit": memory_limit},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise OpenAIRequestError(f"OpenAI containers.create failed: {resp.status_code} {resp.text}")
    data = resp.json()
    container_id = data.get("id")
    if not container_id:
        raise OpenAIRequestError(f"OpenAI containers.create returned no id: {data}")
    return str(container_id)


def delete_container(*, api_key: str, container_id: str) -> None:
    """
    Best-effort Cleanup.
    Siehe: DELETE /v1/containers/{container_id}
    """
    try:
        resp = requests.delete(
            f"{OPENAI_API_BASE}/containers/{container_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        # 404/410 ist ok (bereits weg/expired)
        if resp.status_code >= 400 and resp.status_code not in (404, 410):
            logger.warning("OpenAI containers.delete failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("OpenAI containers.delete exception")


def _extract_output_text(response_json: Dict[str, Any]) -> str:
    """
    Extracts text from Responses API JSON:
    response.output[*].content[*].text
    """
    out_parts: List[str] = []
    for item in (response_json.get("output") or []) or []:
        for c in (item.get("content") or []) or []:
            t = c.get("text")
            if isinstance(t, str) and t.strip():
                out_parts.append(t)
    return "\n".join(out_parts).strip()


def create_mapping_response(
    *,
    api_key: str,
    container_id: str,
    pdf_bytes: bytes,
    customer_payload: Dict[str, Any],
    allowed_customer_keys: List[str],
) -> Dict[str, Any]:
    """
    Ruft GPT-5.2 mit Code Interpreter auf, damit das Modell via Python:
    - interne AcroForm Feldobjekte extrahiert (/T, /FT, IndirectRefs)
    - und diese Felder auf CustomerProfile Keys mappt
    """
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    pdf_file_data = f"data:application/pdf;base64,{pdf_b64}"

    system_prompt = (
        "Du bist ein Assistent für PDF-AcroForm Analyse. Du MUSST das Python-Tool (Code Interpreter) nutzen.\n"
        "Ziel: Extrahiere interne PDF-Formfeld-Objekte (nicht nur Labels) und mappe sie auf Customer-Attribute.\n"
        "Antworte ausschließlich mit einem JSON-Objekt."
    )

    python_snippet = r"""
import json
from glob import glob

pdf_candidates = glob("**/*.pdf", recursive=True)
pdf_path = pdf_candidates[0] if pdf_candidates else "document.pdf"

try:
    from pypdf import PdfReader
except Exception:
    try:
        from PyPDF2 import PdfReader
    except Exception as e:
        raise RuntimeError(f"Keine PDF-Library verfügbar (pypdf/PyPDF2). Original: {e}")

def ref_str(obj):
    try:
        # IndirectObject in pypdf/PyPDF2
        idnum = getattr(obj, "idnum", None)
        gen = getattr(obj, "generation", None)
        if idnum is not None and gen is not None:
            return f"{int(idnum)} {int(gen)} R"
    except Exception:
        pass
    return None

def resolve(obj):
    try:
        return obj.get_object()
    except Exception:
        return obj

reader = PdfReader(pdf_path)
root = reader.trailer.get("/Root") if hasattr(reader, "trailer") else None
if root is None:
    raise RuntimeError("PDF root not found")
root = resolve(root)
acro = root.get("/AcroForm") if hasattr(root, "get") else None
acro = resolve(acro) if acro else None
fields = (acro.get("/Fields") if acro else None) or []

extracted = []
seen = set()

def traverse(field_ref):
    field_obj = resolve(field_ref)
    if field_obj is None or not hasattr(field_obj, "get"):
        return

    # Feldname & Typ
    t = field_obj.get("/T")
    ft = field_obj.get("/FT")
    tu = field_obj.get("/TU")
    field_name = str(t) if t is not None else None
    field_type = str(ft).lstrip("/") if ft is not None else None
    field_label = str(tu) if tu is not None else None

    kids = field_obj.get("/Kids") or []

    # Widget-Rezepte: Kids ohne /T sind oft Widgets; wir sammeln ihre Refs separat
    widget_refs = []
    for k in kids or []:
        r = ref_str(k)
        if r:
            widget_refs.append(r)

    # Entscheide: Dieses Objekt ist ein "echtes" Feld, wenn /T + /FT existieren
    if field_name and field_type:
        key = (field_name, ref_str(field_ref) or "")
        if key not in seen:
            seen.add(key)
            extracted.append(
                {
                    "field_name": field_name,
                    "field_object_ref": ref_str(field_ref),
                    "field_type": field_type,
                    "field_label": field_label,
                    "widget_object_refs": widget_refs,
                }
            )

    # Traverse kids
    for k in kids or []:
        traverse(k)

for f in fields:
    traverse(f)

print(json.dumps({"extracted_fields": extracted}, ensure_ascii=False))
"""

    user_text = (
        "Du erhältst eine PDF-Datei als input_file.\n\n"
        "1) Nutze das Python-Tool und führe diesen Code aus, um interne Felder zu extrahieren:\n"
        f"```python\n{python_snippet}\n```\n\n"
        "2) Nimm die JSON-Ausgabe `extracted_fields` und mappe NUR passende Felder auf diese Customer-Keys:\n"
        + json.dumps(
            {"allowed_customer_keys": allowed_customer_keys, "customer": customer_payload},
            ensure_ascii=False,
            default=str,
        )
        + "\n\n"
        "3) Antworte als JSON-Objekt exakt in dieser Form:\n"
        '{"mappings":[{"field_name":str,"field_object_ref":str|null,"field_type":str|null,"customer_key":str|null,"confidence":float}]}\n\n'
        "Regeln:\n"
        "- `field_name` MUSS exakt aus `extracted_fields[*].field_name` stammen.\n"
        "- `field_object_ref`/`field_type` sollen aus `extracted_fields` übernommen werden.\n"
        "- `customer_key` darf nur aus allowed_customer_keys stammen, sonst null.\n"
        "- Keine Daten erfinden. Wenn unklar -> customer_key=null.\n"
        "- Gib keine Erklärtexte aus, nur JSON."
    )

    body: Dict[str, Any] = {
        "model": "gpt-5.2",
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "code_interpreter", "container": container_id}],
        "tool_choice": "required",
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "filename": "document.pdf", "file_data": pdf_file_data},
                    {"type": "input_text", "text": user_text},
                ],
            },
        ],
    }

    resp = requests.post(
        f"{OPENAI_API_BASE}/responses",
        headers=_headers(api_key),
        json=body,
        timeout=180,
    )
    if resp.status_code >= 400:
        raise OpenAIRequestError(f"OpenAI responses.create failed: {resp.status_code} {resp.text}")
    response_json = resp.json()
    txt = _extract_output_text(response_json)
    if not txt:
        raise OpenAIRequestError(f"OpenAI responses.create returned no output text: {response_json}")
    try:
        return json.loads(txt)
    except Exception as e:
        raise OpenAIRequestError(f"OpenAI response was not valid JSON. Error: {e}. Text: {txt[:2000]}")


def build_pdf_field_mapping(
    *,
    api_key: str,
    pdf_bytes: bytes,
    customer_payload: Dict[str, Any],
    allowed_customer_keys: List[str],
) -> Dict[str, Any]:
    """
    Convenience wrapper: creates container, gets mapping, cleans up.
    """
    container_id: Optional[str] = None
    try:
        container_id = create_container(api_key=api_key, memory_limit="4g")
        return create_mapping_response(
            api_key=api_key,
            container_id=container_id,
            pdf_bytes=pdf_bytes,
            customer_payload=customer_payload,
            allowed_customer_keys=allowed_customer_keys,
        )
    finally:
        if container_id:
            delete_container(api_key=api_key, container_id=container_id)


