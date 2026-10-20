"""OVAK HTTP client ported from verified v4 script (stdlib only)."""
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

LOGIN_URL = "https://zis.ovak.cz/"
EMIS_URL = "https://cz-sitr.suezsmartsolutions.com/eMIS.SE_OVAK/Site_Energie.aspx"
USER_FIELD = "ctl00$ctl00$lvLoginForm$LoginDialog1$edEmail"
PASS_FIELD = "ctl00$ctl00$lvLoginForm$LoginDialog1$edPassword"
LOGIN_BUTTON = "ctl00$ctl00$lvLoginForm$LoginDialog1$btnLogin"
POSTBACKS = (("ctl00$ctl00$MainMenu1$btnConsPlace", ""),)
SSO_LINK_SUFFIX = "btnPortalEmis"
TABLE_ID = "ctl00_PHZonePrincipale_ctl01_TableTableau"
TIMEOUT = 30

class PageParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = {}
        self.action = None
        self.links = []
        self.in_table = False
        self.in_cell = False
        self.row = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and self.action is None:
            self.action = attrs.get('action')
        elif tag == 'input' and attrs.get('type', '').lower() == 'hidden':
            if attrs.get('name'):
                self.hidden[attrs['name']] = attrs.get('value', '')
        elif tag == 'a':
            self.links.append((attrs.get('id', ''), attrs.get('href', '')))
        elif tag == 'table' and attrs.get('id') == TABLE_ID:
            self.in_table = True
        elif self.in_table and tag == 'tr':
            self.row = []
        elif self.in_table and tag in ('td', 'th') and (self.row is not None):
            self.in_cell = True
            self.row.append('')

    def handle_data(self, data):
        if self.in_table and self.in_cell and self.row:
            self.row[-1] += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_cell = False
        elif tag == 'tr' and self.in_table:
            if self.row:
                self.rows.append([cell.strip() for cell in self.row])
            self.row = None
        elif tag == 'table' and self.in_table:
            self.in_table = False

def request(opener, method, url, form=None):
    data = urlencode(form).encode('utf-8') if form is not None else None
    headers = {'User-Agent': 'Mozilla/5.0 (HomeAssistant OVAK client)'}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = Request(url, data=data, headers=headers, method=method)
    with opener.open(req, timeout=TIMEOUT) as response:
        final_url = response.geturl()
        charset = response.headers.get_content_charset() or 'utf-8'
        html = response.read().decode(charset, errors='replace')
    page = PageParser()
    page.feed(html)
    return (final_url, html, page)

def postback(opener, url, page, target, argument):
    form = dict(page.hidden)
    if '__VIEWSTATE' not in form:
        raise RuntimeError('Chybí __VIEWSTATE; nejspíš není načtena ASP.NET stránka')
    form['__EVENTTARGET'] = target
    form['__EVENTARGUMENT'] = argument
    return request(opener, 'POST', urljoin(url, page.action or url), form)

def login(opener, username, password):
    url, html, page = request(opener, 'GET', LOGIN_URL)
    if '__VIEWSTATE' not in page.hidden:
        raise RuntimeError('Na přihlašovací stránce chybí __VIEWSTATE')
    form = dict(page.hidden)
    form.update({USER_FIELD: username, PASS_FIELD: password, LOGIN_BUTTON: 'Vstoupit'})
    url, html, page = request(opener, 'POST', urljoin(url, page.action or url), form)
    if re.search('<input\\b[^>]*name=["\\\']' + re.escape(PASS_FIELD), html, re.I):
        raise RuntimeError('Přihlášení se nezdařilo; zkontroluj údaje/formulář/captcha')
    for target, argument in POSTBACKS:
        present = target in html or target.replace('$', '_') in html
        if not present:
            raise RuntimeError(f'Postback target neexistuje na stránce: {target}')
        url, html, page = postback(opener, url, page, target, argument)
        if '/errorpages/' in url.lower():
            raise RuntimeError(f'OVAK vrátil chybovou stránku: {url}')
    sso_href = next((href for ident, href in page.links if ident.endswith(SSO_LINK_SUFFIX)), None)
    if not sso_href:
        raise RuntimeError('Na stránce odběrných míst nebyl nalezen SSO odkaz btnPortalEmis; výše jsou vypsány dostupné prvky NAV')
    match = re.fullmatch('javascript:__doPostBack\\([\'\\"]([^\'\\"]+)[\'\\"],\\s*[\'\\"]([^\'\\"]*)[\'\\"]\\)', sso_href.strip(), re.IGNORECASE)
    if match:
        target, argument = match.groups()
        url, html, page = postback(opener, url, page, target, argument)
    elif urlparse(sso_href).scheme in ('http', 'https', ''):
        url, html, page = request(opener, 'GET', urljoin(url, sso_href))
    else:
        raise RuntimeError('Neznámý formát SSO odkazu')
    if urlparse(url).hostname == 'zis.ovak.cz':
        patterns = ('(?i)window\\.open\\s*\\(\\s*[\'\\"]([^\'\\"]+)', '(?i)(?:window\\.|document\\.)?location(?:\\.href)?\\s*=\\s*[\'\\"]([^\'\\"]+)', '(?i)[\'\\"](https?://cz-sitr\\.suezsmartsolutions\\.com/[^\'\\"]+)')
        candidates = [match for pattern in patterns for match in re.findall(pattern, html)]
        candidates.extend((href for _, href in page.links))
        trusted = []
        for candidate in candidates:
            candidate = candidate.replace('\\/', '/').replace('&amp;', '&')
            dest = urljoin(url, candidate.strip())
            parsed = urlparse(dest)
            if parsed.scheme == 'https' and parsed.hostname == 'cz-sitr.suezsmartsolutions.com':
                trusted.append(dest)
        if trusted:
            url, html, page = request(opener, 'GET', trusted[0])
    if '/errorpages/' in urlparse(url).path.lower():
        raise RuntimeError('SSO skončilo na chybové stránce OVAK')
    if urlparse(url).path.lower().endswith('/login.aspx'):
        raise RuntimeError('SSO přesměrovalo na přihlašovací stránku')

def fetch_consumption(opener, target):
    url = EMIS_URL + '?' + urlencode({'Affichage': 'ConsoJour', 'Annee': target.year, 'Mois': target.month})
    final_url, _, page = request(opener, 'GET', url)
    if urlparse(final_url).path.lower().endswith('/login.aspx'):
        raise RuntimeError('OVAK/eMIS session není platná ani po SSO')
    if not page.rows:
        raise RuntimeError('Na stránce chybí tabulka denní spotřeby (změna portálu/autentizace)')
    for row in page.rows:
        if len(row) < 2:
            continue
        try:
            day = datetime.strptime(row[0], '%d.%m.%Y').date()
        except ValueError:
            continue
        if day == target:
            raw = row[1].replace('\xa0', '').replace(' ', '').replace(',', '.')
            liters = float(raw)
            return {'date': target.isoformat(), 'liters': liters, 'm3': round(liters / 1000, 3)}
    raise RuntimeError(f'Spotřeba pro {target.isoformat()} zatím není dostupná')

def fetch_days(username: str, password: str, first: date, last: date) -> dict[date, int]:
    """Fetch complete daily consumption for interval, with one SSO login."""
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    login(opener, username, password)
    result = {}
    current = first.replace(day=1)
    while current <= last:
        url = EMIS_URL + '?' + urlencode({
            'Affichage': 'ConsoJour', 'Annee': current.year, 'Mois': current.month,
        })
        final_url, _, page = request(opener, 'GET', url)
        if urlparse(final_url).path.lower().endswith('/login.aspx'):
            raise RuntimeError('eMIS session expired')
        if not page.rows:
            raise RuntimeError(f'Consumption table missing: {current:%Y-%m}')
        for row in page.rows:
            if len(row) < 2:
                continue
            try:
                day = datetime.strptime(row[0], '%d.%m.%Y').date()
            except ValueError:
                continue
            if not first <= day <= last:
                continue
            raw = row[1].replace('\u00a0', '').replace(' ', '').replace(',', '.')
            liters = float(raw)
            if not liters.is_integer() or liters < 0:
                raise RuntimeError(f'Unexpected consumption for {day}: {liters}')
            result[day] = int(liters)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result
