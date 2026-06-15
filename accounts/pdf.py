from io import BytesIO
from decimal import Decimal

MONTHS = [
    'January','February','March','April','May','June',
    'July','August','September','October','November','December',
]

# ─── Number to Words ─────────────────────────────────────────────────────────

_ONES = ['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',
         'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',
         'Seventeen','Eighteen','Nineteen']
_TENS = ['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']

def _convert(n):
    if n == 0:   return ''
    if n < 20:   return _ONES[n] + ' '
    if n < 100:  return _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '') + ' '
    if n < 1000: return _ONES[n // 100] + ' Hundred ' + _convert(n % 100)
    if n < 100000:    return _convert(n // 1000)    + 'Thousand ' + _convert(n % 1000)
    if n < 10000000:  return _convert(n // 100000)  + 'Lakh '     + _convert(n % 100000)
    return _convert(n // 10000000) + 'Crore ' + _convert(n % 10000000)

def _amount_words(amount):
    rupees = int(amount)
    paise  = round((float(amount) - rupees) * 100)
    words  = _convert(rupees).strip() or 'Zero'
    if paise:
        words += f' and {_convert(paise).strip()} Paise'
    return f'INR {words} Only'


# ─── HTML Template ───────────────────────────────────────────────────────────

def _cell(content, extra='', td='td'):
    return f'<{td} style="border:1px solid #000;padding:2px 4px;vertical-align:top;{extra}">{content}</{td}>'

def _fmt(amount):
    """Indian lakh number format: 2,00,000.00 instead of 200,000.00"""
    s = f'{float(amount):.2f}'
    integer_part, decimal_part = s.split('.')
    n = integer_part
    if len(n) <= 3:
        return f'{n}.{decimal_part}'
    last3 = n[-3:]
    rest = n[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f'{",".join(groups)},{last3}.{decimal_part}'

def _addr_html(text, user):
    """Convert ship_to/bill_to TextField to HTML, falling back to user profile."""
    if text and text.strip():
        return text.replace('\n', '<br>')
    parts = [f'<b>{user.name.upper()}</b>']
    if user.company:    parts.append(user.company)
    if user.address:    parts.append(user.address.replace('\n', '<br>'))
    if user.gst_number: parts.append(f'GSTIN/UIN : {user.gst_number}')
    return '<br>'.join(parts)


def _render_html(invoice):
    from django.utils import timezone

    user     = invoice.user
    items    = list(invoice.items.all())
    date_str = invoice.created_at.strftime('%d-%b-%y') if invoice.created_at else timezone.now().strftime('%d-%b-%y')

    ship_to_html = _addr_html(getattr(invoice, 'ship_to', ''), user)
    bill_to_html = _addr_html(getattr(invoice, 'bill_to', ''), user)

    item_rows = ''
    for idx, item in enumerate(items, 1):
        period     = f'{item.service_name.upper()} — {MONTHS[item.month - 1].upper()} {item.year}'
        qty        = float(item.quantity)
        unit_rate  = float(item.amount) / qty if qty else float(item.amount)
        rate_incl  = unit_rate * (1 + int(invoice.gst_rate) / 100)
        qty_label  = f'{qty:.2f} {item.per}'
        item_rows += f'''
        <tr>
          {_cell(idx, 'text-align:center;')}
          {_cell(period)}
          {_cell(item.hsn_code, 'text-align:center;')}
          {_cell(qty_label, 'text-align:center;')}
          {_cell(_fmt(rate_incl), 'text-align:right;')}
          {_cell(_fmt(unit_rate), 'text-align:right;')}
          {_cell(item.per, 'text-align:center;')}
          {_cell(_fmt(item.amount), 'text-align:right;')}
        </tr>'''

    total_qty   = f'{sum(float(i.quantity) for i in items):.2f} Nos'
    hsn_list    = ', '.join(sorted({i.hsn_code for i in items})) or '998311'
    total_words = _amount_words(invoice.total)
    gst_words   = _amount_words(invoice.gst_amount)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @page {{ size:A4; margin:6mm; }}
  body {{ font-family:Helvetica,Arial,sans-serif; font-size:9pt; color:#000; margin:0; padding:0; line-height:1.3; }}
  table {{ width:100%; border-collapse:collapse; }}
  td,th {{ border:1px solid #000; padding:2px 4px; vertical-align:top; }}
  .c {{ text-align:center; }}
  .r {{ text-align:right; }}
  .b {{ font-weight:bold; }}
  h1 {{ font-size:22pt; color:#5d56b7; font-weight:800; margin:0; letter-spacing:1px; }}
  h2 {{ font-size:10pt; margin:2px 0 0; }}
  .title {{ text-align:center; font-weight:bold; font-size:10pt; margin:4px 0 3px; }}
  .footer {{ text-align:center; font-weight:bold; font-size:9pt; margin-top:6px; border-top:1px solid #ccc; padding-top:4px; line-height:1.6; }}
  .generated {{ text-align:center; font-size:8pt; margin-top:3px; }}
</style>
</head>
<body>

<!-- Company Header -->
<div style="text-align:center;margin-bottom:4px;">
  <h1>MIDRUS ASSOCIATE PRIVATE LIMITED</h1>
  <h2>CIN U69200OD2024PTC044993</h2>
</div>

<div class="title">INVOICE</div>

<!-- Seller + Invoice Meta -->
<table>
<tr>
  <td style="width:36%;padding:3px 5px;">
    <b>MIDRUS ASSOCIATE PRIVATE LIMITED</b><br>
    PLOT NO-601/7036<br>
    IGIT ROAD, SARANGA<br>
    DHENKANAL<br>
    ODISHA<br>
    759146<br>
    GSTIN/UIN : 21AARCM7795A1Z9<br>
    State Name : Odisha, Code : 21
  </td>
  <td style="width:64%;padding:0;">
    <table>
      <tr>{_cell('Invoice No.','width:25%')}{_cell(invoice.invoice_number,'width:25%;font-weight:bold;')}{_cell('Dated','width:25%')}{_cell(date_str,'width:25%')}</tr>
      <tr>{_cell('Delivery Note')}{_cell('')}{_cell('Mode/Terms of Payment')}{_cell('')}</tr>
      <tr>{_cell('Reference No. &amp; Date')}{_cell('')}{_cell('Other References')}{_cell('')}</tr>
      <tr>{_cell("Buyer's Order No")}{_cell('')}{_cell('Dated')}{_cell('')}</tr>
      <tr>{_cell('Dispatch Doc No')}{_cell('')}{_cell('Delivery Note Date')}{_cell('')}</tr>
      <tr>{_cell('Dispatched through')}{_cell('')}{_cell('Destination')}{_cell('')}</tr>
      <tr>{_cell('Terms of Delivery')}<td colspan="3" style="border:1px solid #000;padding:2px 4px;"></td></tr>
    </table>
  </td>
</tr>
</table>

<!-- Consignee / Buyer -->
<table>
<tr>
  <td style="width:36%;padding:3px 5px;">
    <span style="font-size:8pt;">Consignee (Ship to)</span><br>
    {ship_to_html}
  </td>
  <td style="width:64%;padding:3px 5px;">
    <span style="font-size:8pt;">Buyer (Bill to)</span><br>
    {bill_to_html}
  </td>
</tr>
</table>

<!-- Items -->
<table>
<thead>
<tr>
  <th class="c" style="width:4%;">Sl No.</th>
  <th class="c" style="width:40%;">Description of Goods</th>
  <th class="c" style="width:10%;">HSN/SAC</th>
  <th class="c" style="width:8%;">Quantity</th>
  <th class="c" style="width:9%;">Rate (Incl. of Tax)</th>
  <th class="c" style="width:9%;">Rate</th>
  <th class="c" style="width:6%;">per</th>
  <th class="c" style="width:14%;">Amount</th>
</tr>
</thead>
<tbody>
  {item_rows}
  <tr>
    <td colspan="7" class="c b">IGST</td>
    <td class="r">{_fmt(invoice.gst_amount)}</td>
  </tr>
  <tr>
    <td colspan="3"></td>
    <td class="c b">{total_qty}</td>
    <td colspan="3"></td>
    <td class="r b">&#8377; {_fmt(invoice.total)}</td>
  </tr>
</tbody>
</table>

<!-- Amount in Words -->
<table>
<tr>
  <td style="border:1px solid #000;border-top:none;padding:2px 5px;width:85%;">Amount Chargeable (in words)</td>
  <td style="border:1px solid #000;border-top:none;border-left:none;padding:2px 5px;text-align:right;font-weight:bold;">E &amp; OE</td>
</tr>
<tr>
  <td colspan="2" style="border:1px solid #000;border-top:none;padding:3px 5px;">
    <b>{total_words}</b>
  </td>
</tr>
</table>

<!-- Tax Summary -->
<table>
<thead>
<tr>
  <th class="c" rowspan="2">HSN/SAC</th>
  <th class="c" rowspan="2">Taxable Value</th>
  <th class="c" colspan="2">IGST</th>
  <th class="c" rowspan="2">Total Tax Amount</th>
</tr>
<tr>
  <th class="c">Rate</th>
  <th class="c">Amount</th>
</tr>
</thead>
<tbody>
  <tr>
    <td class="c">{hsn_list}</td>
    <td class="r">{_fmt(invoice.subtotal)}</td>
    <td class="c">{invoice.gst_rate}%</td>
    <td class="r">{_fmt(invoice.gst_amount)}</td>
    <td class="r">{_fmt(invoice.gst_amount)}</td>
  </tr>
  <tr>
    <td class="b">Total</td>
    <td class="r b">{_fmt(invoice.subtotal)}</td>
    <td></td>
    <td class="r b">{_fmt(invoice.gst_amount)}</td>
    <td class="r b">{_fmt(invoice.gst_amount)}</td>
  </tr>
</tbody>
</table>

<!-- Declaration / Bank / Signature -->
<table>
<tr>
  <td style="width:35%;height:80px;padding:4px;">
    <b>Declaration</b><br>
    We declare that this invoice shows the actual price of the goods described
    and that all particulars are true and correct.
  </td>
  <td style="width:35%;padding:4px;">
    Tax Amount (in words)<br>
    <b>{gst_words}</b><br>
    Company's Bank Details<br>
    Bank Name : STATE BANK OF INDIA<br>
    A/c No : 4333752009<br>
    Branch &amp; IFS Code : TALCHER &amp; SBIN0000192
    {f'<br><i style="font-size:8pt;color:#555;">{invoice.notes}</i>' if invoice.notes else ''}
  </td>
  <td style="width:30%;padding:4px;">
    for MIDRUS ASSOCIATE PRIVATE LIMITED
    <div style="text-align:right;padding-top:40px;">
      ___________________<br>
      Authorised Signatory
    </div>
  </td>
</tr>
</table>

<div class="generated">This is a Computer Generated Invoice</div>

<div class="footer">
  Regd- Office: Plot No-601/7036, AT/PO- Saranga, PS- Parjang, Dist-Dhenkanal-759146<br>
  Mob - 9543253565, 9488222454 &nbsp;&nbsp;&nbsp; Email - info@midrusindia.com
</div>

</body>
</html>'''


def generate_invoice_pdf(invoice):
    from xhtml2pdf import pisa
    html    = _render_html(invoice)
    buffer  = BytesIO()
    result  = pisa.CreatePDF(html, dest=buffer, encoding='utf-8')
    if result.err:
        raise RuntimeError(f'xhtml2pdf error: {result.err}')
    return buffer.getvalue()
