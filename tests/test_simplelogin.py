import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('simplelogin', ROOT / 'simplelogin.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

BOXES = [{'id': 1, 'email': 'me@example.com', 'default': True, 'verified': True, 'nb_alias': 3},
         {'id': 2, 'email': 'other@example.com', 'default': False, 'verified': False, 'nb_alias': 0}]
SUFFIXES = [{'suffix': '.abc@simplelogin.com', 'signed_suffix': '.abc@simplelogin.com.SIG1', 'is_custom': False},
            {'suffix': '@sl.example.com', 'signed_suffix': '@sl.example.com.SIG2', 'is_custom': True}]


def alias(i, email, enabled=True):
    return {'id': i, 'email': email, 'enabled': enabled, 'mailboxes': [BOXES[0]], 'nb_forward': 0, 'nb_block': 0, 'note': None}


class FakeClient(m.Client):
    def __init__(self, aliases=None):
        self.calls = []
        self.aliases = aliases if aliases is not None else [alias(7, 'netflix@sl.example.com')]

    def request(self, method, path, query=None, body=None, raw=False):
        self.calls.append((method, path, query, body))
        if path == '/api/v2/mailboxes':
            return {'mailboxes': BOXES}
        if path == '/api/v5/alias/options':
            return {'can_create': True, 'suffixes': SUFFIXES}
        if path == '/api/v2/aliases':
            page = query['page_id']
            hits = [a for a in self.aliases if not (body or {}).get('query') or body['query'] in a['email']]
            return {'aliases': hits[page * 20:(page + 1) * 20]}
        if path == '/api/v3/alias/custom/new':
            return alias(8, body['alias_prefix'] + body['signed_suffix'].rsplit('.SIG', 1)[0])
        if path.endswith('/toggle'):
            return {'enabled': False}
        if path == '/api/custom_domains':
            return [{'id': 3, 'domain_name': 'sl.example.com', 'is_verified': True, 'catch_all': False, 'mailboxes': [BOXES[0]]}]
        return {}


def run(client, *argv):
    with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()) as e:
        code = m.main(list(argv), client=client)
    return code, o.getvalue(), e.getvalue()


class Tests(unittest.TestCase):
    def test_new_alias_on_custom_domain(self):
        c = FakeClient()
        code, text, _ = run(c, 'alias', 'new', 'amazon', '--domain', 'sl.example.com', '--note', 'Amazon')
        self.assertEqual(code, 0)
        body = [x for x in c.calls if x[1] == '/api/v3/alias/custom/new'][0][3]
        self.assertEqual(body, {'alias_prefix': 'amazon', 'signed_suffix': '@sl.example.com.SIG2', 'mailbox_ids': [1], 'note': 'Amazon'})
        self.assertIn('amazon@sl.example.com', text)

    def test_default_suffix_prefers_custom_domain(self):
        self.assertEqual(m.pick_suffix(SUFFIXES, None)['suffix'], '@sl.example.com')
        self.assertEqual(m.pick_suffix(SUFFIXES, 'simplelogin.com')['suffix'], '.abc@simplelogin.com')
        self.assertIsNone(m.pick_suffix(SUFFIXES, 'unknown.net'))

    def test_unverified_mailbox_refused(self):
        code, _, err = run(FakeClient(), 'alias', 'new', 'x', '--mailbox', 'other@example.com')
        self.assertEqual(code, 1)
        self.assertIn('non vérifiée', err)

    def test_delete_needs_flag(self):
        c = FakeClient()
        code, _, err = run(c, 'alias', 'delete', 'netflix@sl.example.com')
        self.assertEqual(code, 1)
        self.assertFalse(any(x[0] == 'DELETE' for x in c.calls))
        code, _, _ = run(c, 'alias', 'delete', 'netflix@sl.example.com', '--yes-destructive')
        self.assertEqual(code, 0)
        self.assertIn(('DELETE', '/api/aliases/7', None, None), c.calls)

    def test_disable_is_idempotent(self):
        c = FakeClient([alias(7, 'a@sl.example.com', enabled=False)])
        code, text, _ = run(c, 'alias', 'disable', 'a@sl.example.com')
        self.assertIn('déjà', text)
        self.assertFalse(any(x[1].endswith('/toggle') for x in c.calls))

    def test_pagination(self):
        c = FakeClient([alias(i, 'a' + str(i) + '@sl.example.com') for i in range(45)])
        self.assertEqual(len(m.all_aliases(c)), 45)

    def test_catch_all_on_domain(self):
        c = FakeClient()
        run(c, 'domain', 'set', 'sl.example.com', '--catch-all', 'on')
        self.assertIn(('PATCH', '/api/custom_domains/3', None, {'catch_all': True}), c.calls)

    def test_dns_subdomain_records(self):
        recs = m.sl_dns_records('sl.example.com', 'example.com', 'sl-verification=abc')
        names = [(r[0], r[1]) for r in recs]
        self.assertIn(('sl', 'MX'), names)
        self.assertIn(('dkim._domainkey.sl', 'CNAME'), names)
        self.assertIn(('_dmarc.sl', 'TXT'), names)
        with self.assertRaises(m.Error):
            m.sl_dns_records('sl.other.net', 'example.com')

    def test_dns_table_format(self):
        code, text, _ = run(None, 'domain', 'dns', 'sl.example.com', '--format', 'table')
        self.assertEqual(code, 0)
        self.assertIn('sl\tMX\t10 mx1.simplelogin.co', text)
        self.assertNotIn('o2switch dns set', text)

    def test_curl_config_escaping(self):
        self.assertEqual(m.curl_quote('a"b\\c'), '"a\\"b\\\\c"')


if __name__ == '__main__':
    unittest.main()
