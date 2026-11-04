import re
import unicodedata
from io import BytesIO

from PIL import Image, ImageOps

from app.core.config import settings
from app.services.ocr.parser import COMPANY_SUFFIX, EMAIL_RE, PHONE_RE, ROLE_TERMS, WEB_RE, parse_card
from app.services.vision.schemas import CardExtraction

# A larger canvas makes MiniCPM add image tiles on the CPU deployment.
IMAGE_MAX_EDGE = 448
TEMPLATE_WARNING = "This image looks like a card template or mockup. Upload a photo of your completed business card to extract real contact details."
_TEMPLATE = re.compile(
    r'\b(?:business\s+card\s+(?:template|sample)|(?:card\s+)?mockup|editable\s+template|'
    r'company\s+logo|your\s+(?:full\s+)?name|street\s+address\s+here|websitename\.com|'
    r'username|urname@email\.com|yourname@|(?<![\w@.])email\.com)\b', re.I,
)
_LABEL = re.compile(r'^(full name|name|company|organization|job title|title|position|role|address)\s*:\s*(.+)$', re.I)
_LABEL_FIELDS = {'full name': 'full_name', 'name': 'full_name', 'company': 'company', 'organization': 'company',
                 'job title': 'job_title', 'title': 'job_title', 'position': 'job_title', 'role': 'job_title', 'address': 'address'}
_ROLE = re.compile(r'\b(?:' + '|'.join(re.escape(term.strip()) for term in ROLE_TERMS) + r')\b', re.I)
_NAME = re.compile(r"[^\W\d_]+(?:[.'’-][^\W\d_]+)*(?:\s+[^\W\d_]+(?:[.'’-][^\W\d_]+)*){1,3}\.?", re.UNICODE)
_STREET = re.compile(r'^\d+\s+.+\b(?:street|road|avenue|lane|drive|boulevard|st\.?|rd\.?)\b', re.I)


def prepare_image(images: list[tuple[bytes, str]]) -> bytes:
    if not 1 <= len(images) <= 2:
        raise ValueError('MiniCPM requires one or two card images.')
    sides = []
    for data, _ in images:
        with Image.open(BytesIO(data)) as source:
            side = ImageOps.exif_transpose(source).convert('RGB')
            side.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE), Image.Resampling.LANCZOS)
            sides.append(side)
    if len(sides) == 1:
        canvas = sides[0]
    else:
        canvas = Image.new('RGB', (max(side.width for side in sides), sum(side.height for side in sides)), 'white')
        offset = 0
        for side in sides:
            canvas.paste(side, ((canvas.width - side.width) // 2, offset))
            offset += side.height
        canvas.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue()


def parse_transcription(text: str) -> CardExtraction:
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError('Invalid OCR transcription length.')
    if any(unicodedata.category(character) in {'Cc', 'Cs'} and character not in '\n\r\t' for character in text):
        raise ValueError('Unsupported OCR transcription characters.')
    if _TEMPLATE.search(text):
        return CardExtraction(is_template=True, warnings=[TEMPLATE_WARNING])
    rows = [row.strip().strip('#* ').strip() for row in text.splitlines() if row.strip()]
    parsed = parse_card([{'text': row, 'confidence': 0.5} for row in rows], settings.default_phone_region)
    values = {field: None for field in ('full_name', 'company', 'job_title', 'email', 'phone', 'website', 'address')}
    uncertain = []

    def choose(field, candidates):
        distinct = list(dict.fromkeys(candidate for candidate in candidates if candidate))
        if len(distinct) == 1:
            values[field] = distinct[0]
        elif len(distinct) > 1:
            uncertain.append(field)

    choose('email', parsed['candidates']['emails'])
    choose('phone', parsed['candidates']['phones'])
    choose('website', ['https://' + item if not item.lower().startswith(('http://', 'https://')) else item
                       for item in parsed['candidates']['websites']])
    mobile_rows = [row for row in rows if re.match(r'^(?:mobile|mob|cell)\s*:', row, re.I)]
    if mobile_rows:
        mobile = parse_card([{'text': row, 'confidence': 0.5} for row in mobile_rows], settings.default_phone_region)
        if len(mobile['candidates']['phones']) == 1:
            values['phone'] = mobile['candidates']['phones'][0]
            uncertain = [field for field in uncertain if field != 'phone']
    labeled = {field: [] for field in values}
    semantic = []
    for row in rows:
        match = _LABEL.match(row)
        if match:
            labeled[_LABEL_FIELDS[match[1].lower()]].append(match[2].strip())
        elif not (EMAIL_RE.search(row) or PHONE_RE.search(row) or WEB_RE.search(row)):
            semantic.append(row)
    roles = [row for row in semantic if _ROLE.search(row)]
    companies = [row for row in semantic if COMPANY_SUFFIX.search(row) and row not in roles]
    addresses = [row for row in semantic if _STREET.search(row)]
    names = [row for row in semantic if row not in roles + companies + addresses and _NAME.fullmatch(row)]
    for field, candidates in [('full_name', names), ('company', companies), ('job_title', roles), ('address', addresses)]:
        choose(field, labeled[field] or candidates)
    if not any(values.values()) and not uncertain:
        raise ValueError('OCR did not return usable card details.')
    # These fields use text heuristics, so the existing review step must confirm them.
    uncertain.extend(field for field in ('full_name', 'company', 'job_title', 'address') if values[field])
    warnings = ['Review the extracted details against your card before continuing.']
    if any(values[field] is None for field in uncertain):
        warnings.append('Some printed details are ambiguous. Enter the missing fields after checking your card.')
    return CardExtraction(**values, warnings=warnings, uncertain_fields=list(dict.fromkeys(uncertain)))
