#!/usr/bin/env python3
"""simplelogin : pilotage du compte SimpleLogin via son API.

Création, modification et activation d'alias s'exécutent directement (réversibles).
Les suppressions exigent --yes-destructive.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse

APP_DIR = Path.home() / 'Library/Application Support/simplelogin-cli'
CONFIG = APP_DIR / 'config.json'
SERVICE = 'simplelogin-cli.api'
DEFAULT_URL = 'https://app.simplelogin.io'


class Error(Exception):
    pass


def out(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def curl_quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


# ---------------------------------------------------------------- API

class Client:
    def __init__(self, base, key):
        self.base = base.rstrip('/')
        self.key = key

    def request(self, method, path, query=None, body=None, raw=False):
        url = self.base + path + ('?' + urllib.parse.urlencode(query) if query else '')
        # Clé et corps passent par stdin (-K -) pour rester hors des arguments du processus.
        config = 'header = ' + curl_quote('Authentication: ' + self.key) + '\n'
        if body is not None:
            config += 'header = "Content-Type: application/json"\n'
            config += 'data = ' + curl_quote(json.dumps(body, ensure_ascii=True)) + '\n'
        try:
            p = subprocess.run(['curl', '-sS', '--proto', '=https', '--max-redirs', '0', '-m', '30', '-X', method,
                                '-K', '-', '-w', '\n%{http_code}', url],
                               input=config, capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.SubprocessError):
            raise Error('curl introuvable ou bloqué.') from None
        if p.returncode:
            raise Error('Connexion SimpleLogin impossible : ' + (p.stderr.strip().splitlines() or ['curl ' + str(p.returncode)])[-1])
        text, _, code = p.stdout.rpartition('\n')
        if code == '401':
            raise Error('Clé API refusée (401) : relance « simplelogin configure ».')
        if not code.startswith('2'):
            try:
                message = json.loads(text).get('error') or text
            except (ValueError, AttributeError):
                message = text[:200]
            raise Error('SimpleLogin HTTP ' + code + ' : ' + str(message))
        if raw:
            return text
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            raise Error('Réponse SimpleLogin non JSON.') from None

    def get(self, path, query=None):
        return self.request('GET', path, query)

    def post(self, path, body=None, query=None):
        return self.request('POST', path, query, {} if body is None else body)

    def patch(self, path, body):
        return self.request('PATCH', path, None, body)

    def put(self, path, body):
        return self.request('PUT', path, None, body)

    def delete(self, path, body=None):
        return self.request('DELETE', path, None, body)


def load_config():
    if not CONFIG.exists():
        raise Error('Configuration absente : lance « simplelogin configure ».')
    return json.loads(CONFIG.read_text())


def get_client():
    config = load_config()
    p = subprocess.run(['security', 'find-generic-password', '-s', SERVICE, '-a', config['url'], '-w'],
                       capture_output=True, text=True)
    if p.returncode:
        raise Error('Clé API absente du Trousseau : lance « simplelogin configure ».')
    return Client(config['url'], p.stdout.rstrip('\n'))


def configure():
    if sys.platform != 'darwin':
        raise Error('Le stockage Trousseau nécessite macOS.')
    url = input('URL SimpleLogin [' + DEFAULT_URL + '] : ').strip() or DEFAULT_URL
    if not re.fullmatch(r'https://[a-z0-9.-]+(:\d+)?', url):
        raise Error('URL https attendue, sans chemin.')
    key = getpass.getpass('Clé API (saisie masquée) : ')
    if not key or any(c.isspace() for c in key):
        raise Error('Clé invalide.')
    info = Client(url, key).get('/api/user_info')
    # Interactive security prompt keeps the secret out of process arguments.
    command = 'add-generic-password -U -s ' + curl_quote(SERVICE) + ' -a ' + curl_quote(url) + ' -w ' + curl_quote(key) + '\n'
    p = subprocess.run(['security', '-i'], input=command, capture_output=True, text=True)
    if p.returncode:
        raise Error('Enregistrement de la clé dans le Trousseau impossible.')
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_name('config.' + str(os.getpid()) + '.json')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'url': url}, f)
    temp.replace(CONFIG)
    print('Clé valide pour ' + str(info.get('email')) + ', enregistrée dans le Trousseau (service ' + SERVICE + ').')


# ---------------------------------------------------------------- Résolution

def all_aliases(client, query=None, flag=None):
    result, page = [], 0
    while True:
        params = {'page_id': page}
        if flag:
            params[flag] = 'true'
        data = client.post('/api/v2/aliases', {'query': query} if query else {}, params)
        batch = data.get('aliases', [])
        result += batch
        if len(batch) < 20:
            return result
        page += 1


def resolve_alias(client, ref):
    if str(ref).isdigit():
        return client.get('/api/aliases/' + str(ref))
    found = [a for a in all_aliases(client, ref) if a['email'].lower() == ref.lower()]
    if not found:
        raise Error('Alias introuvable : ' + ref)
    return found[0]


def mailboxes(client):
    return client.get('/api/v2/mailboxes')['mailboxes']


def resolve_mailboxes(client, emails):
    boxes = mailboxes(client)
    if not emails:
        return [b['id'] for b in boxes if b.get('default')]
    ids = []
    for email in emails:
        match = [b for b in boxes if b['email'].lower() == email.lower()]
        if not match:
            raise Error('Mailbox inconnue : ' + email + ' (voir « simplelogin mailbox list »).')
        if not match[0].get('verified', True):
            raise Error('Mailbox non vérifiée : ' + email)
        ids.append(match[0]['id'])
    return ids


def resolve_mailbox(client, ref):
    boxes = mailboxes(client)
    match = [b for b in boxes if str(b['id']) == str(ref) or b['email'].lower() == str(ref).lower()]
    if not match:
        raise Error('Mailbox inconnue : ' + str(ref))
    return match[0]


def resolve_domain(client, ref):
    domains = client.get('/api/custom_domains')
    if isinstance(domains, dict):
        domains = domains.get('custom_domains', [])
    match = [d for d in domains if str(d['id']) == str(ref) or d['domain_name'].lower() == str(ref).lower()]
    if not match:
        raise Error('Domaine personnalisé inconnu : ' + str(ref) + ' (il doit d\'abord être ajouté dans l\'interface web).')
    return match[0]


def pick_suffix(suffixes, domain):
    """Choisit le suffixe signé pour un domaine : exact pour un domaine perso, sinon le premier qui finit par @domaine."""
    if not domain:
        custom = [s for s in suffixes if s.get('is_custom')]
        return (custom or suffixes)[0] if suffixes else None
    domain = domain.lower().lstrip('@')
    exact = [s for s in suffixes if s['suffix'].lower() == '@' + domain]
    loose = [s for s in suffixes if s['suffix'].lower().endswith('@' + domain)]
    return (exact or loose or [None])[0]


def alias_line(a):
    state = '' if a.get('enabled', True) else '  [désactivé]'
    boxes = ', '.join(m['email'] for m in a.get('mailboxes', []))
    note = '  « ' + a['note'] + ' »' if a.get('note') else ''
    return str(a['id']) + '  ' + a['email'] + '  ->  ' + boxes + '  (' + str(a.get('nb_forward', 0)) + ' reçus, ' + \
        str(a.get('nb_block', 0)) + ' bloqués)' + state + note


# ---------------------------------------------------------------- Commandes

def cmd_whoami(client, args):
    out({'user': client.get('/api/user_info'), 'stats': client.get('/api/stats')})


def cmd_alias(client, args):
    a = args.action
    if a == 'list':
        flag = 'enabled' if args.enabled else 'disabled' if args.disabled else 'pinned' if args.pinned else None
        rows = all_aliases(client, args.search, flag)
        if args.json:
            out(rows)
        else:
            for row in rows:
                print(alias_line(row))
            print(str(len(rows)) + ' alias', file=sys.stderr)
    elif a == 'show':
        out(resolve_alias(client, args.alias))
    elif a == 'new':
        query = {'hostname': args.hostname} if args.hostname else None
        options = client.get('/api/v5/alias/options', query)
        if not options.get('can_create'):
            raise Error('Création d\'alias impossible (quota atteint ?).')
        suffix = pick_suffix(options.get('suffixes', []), args.domain)
        if not suffix:
            raise Error('Aucun suffixe pour ' + str(args.domain) + '. Disponibles : ' +
                        ', '.join(s['suffix'] for s in options.get('suffixes', [])))
        body = {'alias_prefix': args.prefix, 'signed_suffix': suffix['signed_suffix'],
                'mailbox_ids': resolve_mailboxes(client, args.mailbox)}
        if args.note:
            body['note'] = args.note
        if args.name:
            body['name'] = args.name
        print(alias_line(client.post('/api/v3/alias/custom/new', body, query)))
    elif a == 'random':
        query = {}
        if args.hostname:
            query['hostname'] = args.hostname
        if args.mode:
            query['mode'] = args.mode
        body = {'note': args.note} if args.note else {}
        print(alias_line(client.post('/api/alias/random/new', body, query or None)))
    elif a in ('enable', 'disable'):
        alias = resolve_alias(client, args.alias)
        if alias.get('enabled', True) == (a == 'enable'):
            print(alias['email'] + ' : déjà ' + ('actif' if a == 'enable' else 'désactivé') + '.')
            return
        state = client.post('/api/aliases/' + str(alias['id']) + '/toggle')
        print(alias['email'] + ' : ' + ('actif' if state.get('enabled') else 'désactivé'))
    elif a == 'edit':
        alias = resolve_alias(client, args.alias)
        body = {}
        if args.note is not None:
            body['note'] = args.note
        if args.name is not None:
            body['name'] = args.name
        if args.mailbox:
            body['mailbox_ids'] = resolve_mailboxes(client, args.mailbox)
        if args.pin or args.unpin:
            body['pinned'] = bool(args.pin)
        if not body:
            raise Error('Rien à modifier : --note, --name, --mailbox, --pin ou --unpin.')
        client.patch('/api/aliases/' + str(alias['id']), body)
        print(alias_line(client.get('/api/aliases/' + str(alias['id']))))
    elif a == 'delete':
        alias = resolve_alias(client, args.alias)
        if not args.yes_destructive:
            raise Error('Suppression définitive de ' + alias['email'] + ' : ajoute --yes-destructive. '
                        '« simplelogin alias disable » suffit pour couper la réception.')
        client.delete('/api/aliases/' + str(alias['id']))
        print('Supprimé : ' + alias['email'])
    elif a == 'activity':
        alias = resolve_alias(client, args.alias)
        for act in client.get('/api/aliases/' + str(alias['id']) + '/activities', {'page_id': 0}).get('activities', []):
            print(time.strftime('%Y-%m-%d %H:%M', time.localtime(act['timestamp'])) + '  ' + act['action'] +
                  '  ' + act.get('from', '') + ' -> ' + act.get('to', ''))
    elif a == 'contacts':
        alias = resolve_alias(client, args.alias)
        for c in client.get('/api/aliases/' + str(alias['id']) + '/contacts', {'page_id': 0}).get('contacts', []):
            print(str(c['id']) + '  ' + c['contact'] + '  répondre via ' + str(c.get('reverse_alias_address') or c['reverse_alias']) +
                  ('  [bloqué]' if c.get('block_forward') else ''))
    elif a == 'reply':
        alias = resolve_alias(client, args.alias)
        c = client.post('/api/aliases/' + str(alias['id']) + '/contacts', {'contact': args.contact})
        print('Écris à ' + str(c.get('reverse_alias_address') or c['reverse_alias']) + ' : le mail partira de ' + alias['email'] + '.')


def cmd_mailbox(client, args):
    a = args.action
    if a == 'list':
        for b in mailboxes(client):
            print(str(b['id']) + '  ' + b['email'] + ('  [défaut]' if b.get('default') else '') +
                  ('' if b.get('verified', True) else '  [non vérifiée]') + '  ' + str(b.get('nb_alias', 0)) + ' alias')
    elif a == 'add':
        b = client.post('/api/mailboxes', {'email': args.email})
        print('Mailbox ' + b['email'] + ' ajoutée : clique le lien de vérification reçu dans cette boîte.')
    elif a == 'default':
        b = resolve_mailbox(client, args.mailbox)
        client.put('/api/mailboxes/' + str(b['id']), {'default': True})
        print('Mailbox par défaut : ' + b['email'])
    elif a == 'delete':
        b = resolve_mailbox(client, args.mailbox)
        if b.get('default'):
            raise Error('Impossible de supprimer la mailbox par défaut.')
        target = resolve_mailbox(client, args.transfer_to)['id'] if args.transfer_to else -1
        if not args.yes_destructive:
            raise Error('Suppression de ' + b['email'] + ('' if args.transfer_to else ' ET de ses ' + str(b.get('nb_alias', 0)) + ' alias') +
                        ' : ajoute --yes-destructive (ou --transfer-to pour garder les alias).')
        client.delete('/api/mailboxes/' + str(b['id']), {'transfer_aliases_to': target})
        print('Mailbox supprimée : ' + b['email'])


def sl_dns_records(domain, zone, verification=None):
    """Records DNS demandés par SimpleLogin pour un domaine perso, relatifs à la zone o2switch."""
    domain, zone = domain.lower().rstrip('.'), zone.lower().rstrip('.')
    if domain != zone and not domain.endswith('.' + zone):
        raise Error(domain + ' n\'appartient pas à la zone ' + zone + '.')
    sub = domain[:-len(zone)].rstrip('.')
    def name(prefix):
        return '.'.join(p for p in (prefix, sub) if p) or '@'
    records = []
    if verification:
        records.append((name(''), 'TXT', verification, ['--add']))
    records += [
        (name(''), 'MX', '10 mx1.simplelogin.co', ['--add']),
        (name(''), 'MX', '20 mx2.simplelogin.co', ['--add']),
        # --add : vérification et SPF cohabitent en TXT au même nom.
        (name(''), 'TXT', 'v=spf1 include:simplelogin.co ~all', ['--add']),
        (name('dkim._domainkey'), 'CNAME', 'dkim._domainkey.simplelogin.co', []),
        (name('dkim02._domainkey'), 'CNAME', 'dkim02._domainkey.simplelogin.co', []),
        (name('dkim03._domainkey'), 'CNAME', 'dkim03._domainkey.simplelogin.co', []),
        (name('_dmarc'), 'TXT', 'v=DMARC1; p=quarantine; pct=100; adkim=s; aspf=s', []),
    ]
    return records


def cmd_domain(client, args):
    a = args.action
    if a == 'list':
        domains = client.get('/api/custom_domains')
        if isinstance(domains, dict):
            domains = domains.get('custom_domains', [])
        for d in domains:
            print(str(d['id']) + '  ' + d['domain_name'] + ('' if d.get('is_verified') else '  [non vérifié]') +
                  ('  catch-all' if d.get('catch_all') else '') + '  ' + str(d.get('nb_alias', 0)) + ' alias  -> ' +
                  ', '.join(m['email'] for m in d.get('mailboxes', [])))
    elif a == 'set':
        d = resolve_domain(client, args.domain)
        body = {}
        if args.catch_all:
            body['catch_all'] = args.catch_all == 'on'
        if args.random_prefix:
            body['random_prefix_generation'] = args.random_prefix == 'on'
        if args.name is not None:
            body['name'] = args.name
        if args.mailbox:
            body['mailbox_ids'] = resolve_mailboxes(client, args.mailbox)
        if not body:
            raise Error('Rien à modifier : --catch-all, --random-prefix, --name ou --mailbox.')
        client.patch('/api/custom_domains/' + str(d['id']), body)
        print('Domaine ' + d['domain_name'] + ' mis à jour : ' + json.dumps(body, ensure_ascii=False))
    elif a == 'trash':
        d = resolve_domain(client, args.domain)
        for x in client.get('/api/custom_domains/' + str(d['id']) + '/trash').get('aliases', []):
            print(x['alias'] + '  supprimé le ' + time.strftime('%Y-%m-%d', time.localtime(x['deletion_timestamp'])))


def cmd_dns(args):
    zone = args.zone or '.'.join(args.domain.split('.')[-2:])
    print('# Records SimpleLogin pour ' + args.domain + ' (zone ' + zone + '). Rien n\'est exécuté, les commandes sont affichées.')
    for name, rtype, value, flags in sl_dns_records(args.domain, zone, args.verification):
        if args.format == 'table':
            print(name + '\t' + rtype + '\t' + value)
        else:
            print(' '.join(['o2switch', 'dns', 'set', zone, name, rtype, json.dumps(value)] + flags))
    if not args.verification:
        print('# Ajoute --verification "sl-verification=..." (code affiché par SimpleLogin) pour le TXT de propriété.')
    if args.domain.lower().rstrip('.') == zone:
        print('# Domaine racine : le SPF et le MX existants doivent être fusionnés à la main (--match).')


def cmd_setting(client, args):
    if args.action == 'show':
        out({'settings': client.get('/api/setting'), 'domains': client.get('/api/v2/setting/domains')})
        return
    body = {}
    for pair in args.pairs:
        if '=' not in pair:
            raise Error('clé=valeur attendu : ' + pair)
        key, value = pair.split('=', 1)
        body[key] = {'true': True, 'false': False}.get(value, value)
    out(client.patch('/api/setting', body))


def build_parser():
    p = argparse.ArgumentParser(prog='simplelogin', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('configure', help='Enregistrer la clé API (Trousseau)')
    sub.add_parser('whoami', help='Compte et statistiques')

    a = sub.add_parser('alias', help='Alias')
    asub = a.add_subparsers(dest='action', required=True)
    s = asub.add_parser('list'); s.add_argument('search', nargs='?')
    g = s.add_mutually_exclusive_group(); g.add_argument('--enabled', action='store_true'); g.add_argument('--disabled', action='store_true'); g.add_argument('--pinned', action='store_true')
    s.add_argument('--json', action='store_true')
    s = asub.add_parser('show'); s.add_argument('alias', help='adresse ou id')
    s = asub.add_parser('new', help='Alias personnalisé : préfixe + domaine')
    s.add_argument('prefix'); s.add_argument('--domain', help='ex. sl.example.com ; défaut : premier domaine perso')
    s.add_argument('--mailbox', action='append', help='répétable ; défaut : mailbox par défaut')
    s.add_argument('--note'); s.add_argument('--name', help='nom d\'expéditeur'); s.add_argument('--hostname', help='site associé')
    s = asub.add_parser('random', help='Alias aléatoire')
    s.add_argument('--note'); s.add_argument('--mode', choices=['word', 'uuid']); s.add_argument('--hostname')
    for name in ('enable', 'disable', 'activity', 'contacts'):
        s = asub.add_parser(name); s.add_argument('alias')
    s = asub.add_parser('edit'); s.add_argument('alias'); s.add_argument('--note'); s.add_argument('--name')
    s.add_argument('--mailbox', action='append'); g = s.add_mutually_exclusive_group(); g.add_argument('--pin', action='store_true'); g.add_argument('--unpin', action='store_true')
    s = asub.add_parser('delete'); s.add_argument('alias'); s.add_argument('--yes-destructive', action='store_true')
    s = asub.add_parser('reply', help='Adresse pour écrire à un contact depuis l\'alias'); s.add_argument('alias'); s.add_argument('contact')

    m = sub.add_parser('mailbox', help='Boîtes de réception')
    msub = m.add_subparsers(dest='action', required=True)
    msub.add_parser('list')
    s = msub.add_parser('add'); s.add_argument('email')
    s = msub.add_parser('default'); s.add_argument('mailbox')
    s = msub.add_parser('delete'); s.add_argument('mailbox'); s.add_argument('--transfer-to'); s.add_argument('--yes-destructive', action='store_true')

    d = sub.add_parser('domain', help='Domaines personnalisés')
    dsub = d.add_subparsers(dest='action', required=True)
    dsub.add_parser('list')
    s = dsub.add_parser('set'); s.add_argument('domain'); s.add_argument('--catch-all', choices=['on', 'off'])
    s.add_argument('--random-prefix', choices=['on', 'off']); s.add_argument('--name'); s.add_argument('--mailbox', action='append')
    s = dsub.add_parser('trash'); s.add_argument('domain')
    s = dsub.add_parser('dns', help='Records DNS à poser (commandes o2switch ou tableau)')
    s.add_argument('domain'); s.add_argument('--zone'); s.add_argument('--verification')
    s.add_argument('--format', choices=['o2switch', 'table'], default=os.environ.get('SIMPLELOGIN_DNS_FORMAT', 'o2switch'),
                   help='o2switch : commandes `o2switch dns set` ; table : nom, type, valeur séparés par des tabulations (autre hébergeur DNS). Défaut : $SIMPLELOGIN_DNS_FORMAT ou o2switch')

    st = sub.add_parser('setting', help='Réglages du compte')
    ssub = st.add_subparsers(dest='action', required=True)
    ssub.add_parser('show')
    s = ssub.add_parser('set'); s.add_argument('pairs', nargs='+', help='clé=valeur')

    e = sub.add_parser('export', help='Export CSV des alias')
    return p


def main(argv=None, client=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'configure':
            configure()
            return 0
        if args.command == 'domain' and args.action == 'dns':
            cmd_dns(args)
            return 0
        client = client or get_client()
        if args.command == 'export':
            sys.stdout.write(client.request('GET', '/api/export/aliases', raw=True))
            return 0
        {'whoami': cmd_whoami, 'alias': cmd_alias, 'mailbox': cmd_mailbox, 'domain': cmd_domain,
         'setting': cmd_setting}[args.command](client, args)
    except Error as e:
        print('Erreur : ' + str(e), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as e:
        print('Erreur : ' + type(e).__name__ + ' : ' + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
