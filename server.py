import os, re, json, base64
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='.', static_url_path='')

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO   = 'ataragin-png/Divritoah'
BRANCH = 'main'
PASSWORD = 'Torah613'
GITHUB_API = 'https://api.github.com'

CATEGORIES = [
    "פרשת השבוע", "מועדים וזמנים", "רפואה והלכה",
    "אמונה והשקפה", "הלכה ומשפט", "ברית מילה"
]

# ── GitHub helpers ─────────────────────────────────────────────────────────

def gh_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }

def gh_get(path):
    import requests as req
    r = req.get(f'{GITHUB_API}/repos/{REPO}/contents/{path}',
                headers=gh_headers(), params={'ref': BRANCH})
    r.raise_for_status()
    d = r.json()
    return base64.b64decode(d['content']).decode('utf-8'), d['sha']

def gh_put(path, content_bytes, message, sha=None):
    import requests as req
    payload = {
        'message': message,
        'content': base64.b64encode(content_bytes).decode(),
        'branch': BRANCH
    }
    if sha:
        payload['sha'] = sha
    r = req.put(f'{GITHUB_API}/repos/{REPO}/contents/{path}',
                headers=gh_headers(), json=payload)
    r.raise_for_status()
    return r.json()

# ── PDF generation ─────────────────────────────────────────────────────────

def make_pdf(title, meta, body):
    from weasyprint import HTML
    paragraphs = ''.join(
        f'<p>{line}</p>' for line in body.strip().splitlines() if line.strip()
    )
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head><meta charset="utf-8"/>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap');
  body {{ font-family: 'Frank Ruhl Libre', serif; direction: rtl; text-align: right;
          margin: 40px 50px; font-size: 14pt; line-height: 1.85; color: #2c1f0e; }}
  h1   {{ font-size: 22pt; margin-bottom: 6px; }}
  .sub {{ color: #6b5340; font-size: 12pt; border-bottom: 1px solid #ddc99e;
          padding-bottom: 10px; margin-bottom: 24px; }}
  p    {{ margin: 0 0 12px; }}
</style></head>
<body>
  <h1>{title}</h1>
  {'<p class="sub">' + meta + '</p>' if meta else ''}
  {paragraphs}
</body></html>"""
    return HTML(string=html).write_pdf()

# ── Filename helper ─────────────────────────────────────────────────────────

HEB = {'א':'a','ב':'b','ג':'g','ד':'d','ה':'h','ו':'v','ז':'z','ח':'ch',
       'ט':'t','י':'y','כ':'k','ך':'k','ל':'l','מ':'m','ם':'m','נ':'n',
       'ן':'n','ס':'s','ע':'a','פ':'p','ף':'p','צ':'tz','ץ':'tz','ק':'k',
       'ר':'r','ש':'sh','ת':'t'}

def make_filename(title):
    out = ''.join(HEB.get(c, c if c.isascii() and c.isalnum() else '-') for c in title)
    out = re.sub(r'-+', '-', out).strip('-').lower()[:35]
    ts  = datetime.now().strftime('%Y%m%d%H%M')
    return f'{out or "dvar"}-{ts}'

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')

@app.route('/api/publish', methods=['POST'])
def publish():
    # Auth
    if request.form.get('password', '') != PASSWORD:
        return jsonify({'error': 'סיסמה שגויה'}), 403

    title    = request.form.get('title', '').strip()
    meta     = request.form.get('meta', '').strip()
    category = request.form.get('category', '').strip()
    body     = request.form.get('body_text', '').strip()

    if not title:
        return jsonify({'error': 'חסרה כותרת'}), 400
    if category not in CATEGORIES:
        return jsonify({'error': 'קטגוריה לא תקינה'}), 400
    if not GITHUB_TOKEN:
        return jsonify({'error': 'GITHUB_TOKEN לא מוגדר'}), 500

    # PDF
    uploaded = request.files.get('pdf_file')
    if uploaded and uploaded.filename:
        pdf_bytes = uploaded.read()
    elif body:
        try:
            pdf_bytes = make_pdf(title, meta, body)
        except Exception as e:
            return jsonify({'error': f'שגיאה ביצירת PDF: {e}'}), 500
    else:
        return jsonify({'error': 'יש להעלות PDF או להכניס טקסט'}), 400

    slug     = make_filename(title)
    pdf_path = f'files/{slug}.pdf'

    # Upload PDF
    try:
        gh_put(pdf_path, pdf_bytes, f'Add dvar torah PDF: {title}')
    except Exception as e:
        return jsonify({'error': f'שגיאה בהעלאת PDF: {e}'}), 500

    # Update divrei-torah.html FILES array
    try:
        html, sha = gh_get('divrei-torah.html')
        entry = (
            f'  {{ title: {json.dumps(title, ensure_ascii=False)}, '
            f'meta: {json.dumps(meta, ensure_ascii=False)}, '
            f'file: "{pdf_path}", '
            f'category: {json.dumps(category, ensure_ascii=False)} }}'
        )
        new_html = re.sub(
            r'(const FILES\s*=\s*\[)',
            r'\1\n' + entry + ',',
            html, count=1
        )
        if new_html == html:
            return jsonify({'error': 'לא נמצא מערך FILES בקובץ'}), 500
        gh_put('divrei-torah.html', new_html.encode('utf-8'),
               f'Add dvar torah: {title}', sha=sha)
    except Exception as e:
        return jsonify({'error': f'שגיאה בעדכון divrei-torah.html: {e}'}), 500

    return jsonify({
        'success': True,
        'message': f'"{title}" פורסם בהצלחה!',
        'live_url': 'https://ataragin-png.github.io/Divritoah/divrei-torah.html'
    })

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
