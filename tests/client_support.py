"""RPA 客户端测试支撑：合成门户 + 真实 Chromium，证据写入临时目录。"""
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from source.app import Site
from source.common import server
from client.portal import PortalPage
from client.workflow import RpaWorkflow
from client.evidence import Evidence


class ClientBrowserTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.httpd = server(self.site)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.httpd.server_port)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.evidence_dir = Path(self._tmp.name) / 'evidence'
        self.pw = sync_playwright().start()
        self.chromium = self.pw.chromium.launch(headless=True, args=['--no-sandbox'])
        self.context = self.chromium.new_context(accept_downloads=True)
        self.tab = self.context.new_page()
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.chromium.close)
        self.addCleanup(self.context.close)
        self.evidence = Evidence(self.evidence_dir, 'co-create-alpha')
        self.portal = PortalPage(self.tab, self.base, self.evidence, timeout_ms=8000)
        self.wf = RpaWorkflow(self.portal, self.evidence)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def control(self, event, **kwargs):
        body = json.dumps({'event': event, **kwargs}).encode()
        req = urllib.request.Request(
            self.base + '/__control', data=body,
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)

    def full_intent(self, **overrides):
        from client.model import Intent
        raw = {
            'application_reference': 'co-create-alpha',
            'actor': 'technical',
            'technical': {
                'title': '区域智能试验',
                'scopes': ['hospital', 'public'],
                'mode': 'trial',
                'data_use': '脱敏后院内试验',
                'notice': '点位周边告知',
            },
            'materials': ['shared', 'data', 'points'],
        }
        if overrides:
            raw['technical'].update(overrides.get('technical', {}))
            if 'materials' in overrides:
                raw['materials'] = overrides['materials']
        return Intent.from_mapping(raw)
