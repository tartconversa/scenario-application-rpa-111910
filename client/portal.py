"""Chromium 页面适配层：经 Playwright 驱动真实页面，不直接调用门户 API。

定位一律使用稳定字段标识（#title、.scope[value=...]、#mode 等），
显示名称变化不影响定位；场景方字段（#partner）只读观察，从不写入。
"""
from dataclasses import dataclass
import json

from client.exceptions import RetiredEnumError
from client.model import (
    TECHNICAL_FIELD_IDS, SCOPE_IDS,
    applicable_fields,
)


@dataclass
class PageState:
    """从真实页面读回的状态（资料员所见即所得）。"""

    revision: int
    dictionary: int
    confirmed: int
    technical: dict
    materials: tuple
    partner: dict
    mode_options: tuple
    mode_label: str
    obligations_text: str
    field_labels: dict

    @property
    def confirmation_current(self):
        return self.confirmed == self.revision


@dataclass
class SaveOutcome:
    """一次保存/提交点击的真实结果。"""

    kind: str                  # saved / conflict / error / accepted / uncertain
    status_code: object = None
    revision: object = None
    raw_text: str = ''
    error_code: str = ''
    detail: dict = None

    @property
    def persisted_unknown(self):
        # 答复丢失（503/超时/导航中断）时，写入是否落盘不能凭猜测认定。
        return self.kind == 'uncertain'


class PortalPage:
    def __init__(self, page, base_url, evidence=None, timeout_ms=10000):
        self.page = page
        self.base_url = base_url.rstrip('/')
        self.evidence = evidence
        self.timeout_ms = timeout_ms

    def open(self):
        self._log('open', self.base_url + '/')
        self.page.goto(self.base_url + '/', timeout=self.timeout_ms)
        self.page.wait_for_selector('#title', timeout=self.timeout_ms)
        if self.evidence:
            self.evidence.capture(self.page, 'opened')
        return self.read_state()

    def open_history(self):
        self._log('open_history', '/history')
        self.page.goto(self.base_url + '/history', timeout=self.timeout_ms)
        self.page.wait_for_selector('#history', timeout=self.timeout_ms)
        text = self.page.locator('#history').inner_text()
        if self.evidence:
            self.evidence.capture(self.page, 'history')
        return json.loads(text)

    def _log(self, action, detail=''):
        if self.evidence:
            self.evidence.log(action, detail)

    def read_state(self):
        data = self.page.evaluate(
            """() => {
              const q = s => document.querySelector(s);
              const num = s => {
                const m = (q(s)?.textContent || '').match(/(\\d+)/);
                return m ? Number(m[1]) : null;
              };
              const labelFor = id => {
                const el = q('#' + id);
                if (!el) return id;
                const lab = el.closest('label');
                if (!lab) return id;
                // 只取 label 的直接文本节点，避免 select 的选项文本混入显示名称。
                const text = Array.from(lab.childNodes)
                  .filter(n => n.nodeType === Node.TEXT_NODE)
                  .map(n => n.textContent).join('').trim();
                return text || id;
              };
              return {
                revision: num('#revision'),
                dictionary: num('#dictionary'),
                confirmed: num('#confirmation'),
                technical: {
                  title: q('#title').value,
                  scopes: Array.from(document.querySelectorAll('.scope:checked'), x => x.value),
                  data_use: q('#data_use').value,
                  notice: q('#notice').value,
                  mode: q('#mode').value,
                },
                materials: q('#materials').value.split(',').map(x => x.trim()).filter(Boolean),
                partner: JSON.parse(q('#partner').textContent),
                mode_options: Array.from(q('#mode').options, o => o.value),
                mode_label: labelFor('mode'),
                obligations: q('#obligations').textContent,
                field_labels: Object.fromEntries(
                  ['title','data_use','notice','mode'].map(id => [id, labelFor(id)])
                ),
              };
            }"""
        )
        return PageState(
            revision=data['revision'],
            dictionary=data['dictionary'],
            confirmed=data['confirmed'],
            technical=data['technical'],
            materials=tuple(data['materials']),
            partner=data['partner'],
            mode_options=tuple(data['mode_options']),
            mode_label=data['mode_label'],
            obligations_text=data['obligations'],
            field_labels=data['field_labels'],
        )

    def fill_technical(self, technical, current_state=None):
        """按字段标识把技术方取值写入页面；场景方字段绝不触碰。

        撤去范围时只清空不再适用的触发字段（data_use/notice），
        另一范围仍适用的字段保留其值。
        """
        state = current_state or self.read_state()
        target = technical
        if target.mode not in state.mode_options:
            # 已失效枚举（如字典淘汰 pilot）不得自动换成第一个选项。
            raise RetiredEnumError('mode', target.mode, state.mode_options)
        self._log('fill_title', target.title)
        self.page.fill('#title', target.title)

        # 范围勾选：以目标集合为准增删，触发页面自带的条件展开/材料义务刷新。
        for scope in SCOPE_IDS:
            checked = self.page.locator(f'.scope[value="{scope}"]').is_checked()
            want = scope in target.scopes
            if want and not checked:
                self._log('scope_check', scope)
                self.page.check(f'.scope[value="{scope}"]')
            elif checked and not want:
                self._log('scope_uncheck', scope)
                self.page.uncheck(f'.scope[value="{scope}"]')

        applied = applicable_fields(target.scopes)
        # 撤去范围后，由它触发的字段输入框在页面上隐藏但仍存在于提交负载中，
        # 需显式清空（隐藏元素不能用 fill，走页面 JS 赋值）。
        for fid, selector in (('data_use', '#data_use'), ('notice', '#notice')):
            if fid not in applied:
                self._log('clear_triggered_field', fid)
                self.page.evaluate(f's => document.querySelector(s).value = ""', selector)
            elif fid == 'data_use':
                self._log('fill_data_use', target.data_use)
                self.page.fill('#data_use', target.data_use)
            elif fid == 'notice':
                self._log('fill_notice', target.notice)
                self.page.fill('#notice', target.notice)

        # 下拉按稳定 option 值选择；失效值已在前面拦截。
        self._log('select_mode', f'{target.mode}（显示名称：{state.mode_label}）')
        self.page.select_option('#mode', target.mode)
        return self.read_state()

    def fill_materials(self, materials):
        text = ','.join(materials)
        self._log('fill_materials', text)
        self.page.fill('#materials', text)
        return self.read_state()

    def save_draft(self):
        return self._act('#save', 'save_draft')

    def submit(self):
        return self._act('#submit', 'submit')

    def _act(self, selector, action):
        self._log('click', action)
        try:
            self.page.click(selector, timeout=self.timeout_ms)
            # 等待 #result 出现答复文本（页面 fetch 完成后写入）。
            self.page.wait_for_function(
                "() => document.querySelector('#result').textContent.trim().length > 0",
                timeout=self.timeout_ms,
            )
        except Exception as exc:
            # 点击后跳转/答复超时：不能据此认定未保存，标记为不确定并交由复核流程。
            self._log('reply_uncertain', str(exc))
            return SaveOutcome(kind='uncertain', raw_text='', error_code='reply_lost',
                               detail={'reason': str(exc)})
        raw = self.page.locator('#result').inner_text()
        return self._classify(raw, action)

    def _classify(self, raw, action):
        try:
            payload = json.loads(raw)
        except ValueError:
            return SaveOutcome(kind='error', raw_text=raw, error_code='unparseable_reply')
        if isinstance(payload, dict) and 'error' in payload:
            code = payload['error']
            if code == 'revision_conflict':
                return SaveOutcome('conflict', status_code=409,
                                   revision=payload.get('current'),
                                   raw_text=raw, error_code=code, detail=payload)
            if code == 'gateway_after_save':
                # 门户语义：写入已完成后答复丢失。
                return SaveOutcome('uncertain', status_code=503,
                                   raw_text=raw, error_code=code, detail=payload)
            kind = 'accepted' if False else 'error'
            return SaveOutcome(kind, raw_text=raw, error_code=code, detail=payload)
        if action == 'submit' and isinstance(payload, dict) and 'application' in payload:
            return SaveOutcome('accepted', revision=payload.get('revision'),
                               raw_text=raw, detail=payload)
        if action == 'save_draft' and isinstance(payload, dict) and 'saved_revision' in payload:
            return SaveOutcome('saved', revision=payload['saved_revision'], raw_text=raw)
        return SaveOutcome('error', raw_text=raw, error_code='unknown_reply',
                           detail=payload if isinstance(payload, dict) else None)

    def reload(self):
        self._log('reload')
        # 全新空白页上 reload 是空操作，需显式 goto；已有导航历史才真正刷新。
        if self.page.url == 'about:blank':
            self.page.goto(self.base_url + '/', timeout=self.timeout_ms)
        else:
            self.page.reload(timeout=self.timeout_ms)
        self.page.wait_for_selector('#title', timeout=self.timeout_ms)
        if self.evidence:
            self.evidence.capture(self.page, 'reloaded')
        return self.read_state()

    def verify_persisted(self, technical, materials):
        """重新读页核对页面实际保存内容是否等于预期（用于答复丢失后的复核）。"""
        state = self.reload()

        def page_val(k):
            val = state.technical.get(k, [] if k == 'scopes' else '')
            return tuple(val) if k == 'scopes' else val

        def want_val(k):
            return tuple(technical.scopes) if k == 'scopes' else getattr(technical, k)

        same_tech = all(page_val(k) == want_val(k) for k in TECHNICAL_FIELD_IDS)
        same_materials = tuple(state.materials) == tuple(materials)
        return {
            'persisted': bool(same_tech and same_materials),
            'page_revision': state.revision,
            'technical_match': same_tech,
            'materials_match': same_materials,
            'state': state,
        }
