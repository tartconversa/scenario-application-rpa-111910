"""RPA 客户端的可重复浏览器检查：真实 Chromium 驱动合成门户。

覆盖：条件字段联动、双方编辑相遇的修订冲突、失效枚举不兜底、
撤范围的义务裁剪、答复丢失不重复建档、确认按修订生效、定向补正与历史。
"""
import json
import unittest
from pathlib import Path

from client.exceptions import (
    RetiredEnumError, IncompleteDraft, PartnerConfirmationRequired,
    PortalError,
)
from client.model import (
    Intent, Correction, TechnicalFields, required_materials,
    reconcile_materials,
)
from tests.client_support import ClientBrowserTest


class ModelUnitTest(unittest.TestCase):
    def test_required_materials_union_and_shared(self):
        self.assertEqual(required_materials([]), set())
        self.assertEqual(required_materials(['hospital']), {'shared', 'data'})
        self.assertEqual(required_materials(['public']), {'shared', 'points'})
        self.assertEqual(
            required_materials(['hospital', 'public']),
            {'shared', 'data', 'points'},
        )

    def test_reconcile_materials_keeps_shared_for_other_scope(self):
        # 撤去 hospital：data 撤下，shared 仍被 public 使用而保留。
        keep, drop = reconcile_materials(
            ('shared', 'data', 'points'), ['public'], ('shared', 'points'))
        self.assertEqual(keep, ('shared', 'points'))
        self.assertEqual(drop, ('data',))
        # 两个范围都撤去：shared 也不再需要。
        keep2, drop2 = reconcile_materials(('shared', 'data'), [], ())
        self.assertEqual(keep2, ())
        self.assertEqual(set(drop2), {'shared', 'data'})

    def test_intent_rejects_non_technical_actor(self):
        with self.assertRaises(ValueError):
            Intent.from_mapping({'application_reference': 'x', 'actor': 'scenario',
                                 'technical': {}})


class FullFlowBrowserTest(ClientBrowserTest):
    def test_01_import_reconcile_and_submit_full_application(self):
        intent = self.full_intent()
        # 先做只读核对：页面空白时应报告待填项，且不产生任何保存。
        state = self.portal.open()
        report = self.wf.reconcile(intent, state)
        self.assertFalse(report.ready_to_submit)
        self.assertTrue(any(r['status'] == 'pending_fill' for r in report.field_rows))
        self.assertEqual(self.site.state['history'], [])

        state, attempts = self.wf.save_intent(intent)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(state.revision, 2)
        # 场景方字段原样保留，技术方负载不含 owner/condition。
        self.assertEqual(state.partner['owner'], '场景单位甲')
        self.assertEqual(state.partner['condition'], '白天试验')

        # 未确认时正式提交被门禁拦截，且不产生受理记录。
        with self.assertRaises(PartnerConfirmationRequired):
            self.wf.submit(intent)
        self.assertIsNone(self.site.state['receipt'])

        # 场景方在另一会话针对当前修订确认后放行，返回稳定申请号。
        self.control('confirm')
        receipt = self.wf.submit(intent)
        self.assertEqual(receipt.application, 'APP-001')
        self.assertEqual(receipt.history_entry['action'], 'accepted')

        history = self.wf.query_history()
        self.assertEqual(history['application'], 'APP-001')
        self.assertTrue(any(h['action'] == 'accepted' for h in history['timeline']))
        # 证据落盘：保存与受理均有实际页面依据。
        evidence = json.loads((self.evidence_dir / 'evidence.json').read_text('utf-8'))
        self.assertTrue(any(s['status'] == 'saved' for s in evidence['saves']))
        self.assertTrue(evidence['receipts'])
        self.assertTrue(list(self.evidence_dir.glob('*.png')))

    def test_02_partner_edits_during_save_conflict_keeps_new_condition(self):
        intent = self.full_intent()
        # 工作流先打开页面，页面 JS baseline 固定为打开时的修订 1。
        self.wf.portal.open()
        # 场景方在另一会话修改条件，门户修订前进到 2；当前页仍携修订 1，保存必遇 409。
        self.control('scenario_edit', condition='夜间试验')
        state, attempts = self.wf.save_intent(intent, reopen=False)
        # 冲突后自动重读页面并按最新修订重试成功，没有新建第二份申请。
        self.assertIn('conflict', [a.kind for a in attempts])
        self.assertEqual(attempts[-1].kind, 'saved')
        self.assertEqual(state.partner['condition'], '夜间试验')
        self.assertEqual(state.technical['title'], '区域智能试验')
        # 没有重建第二份申请。
        saves = [h for h in self.site.state['history'] if h['action'] == 'saved']
        self.assertGreaterEqual(len(saves), 1)
        self.assertIsNone(self.site.state['receipt'])
        # 技术方再改字段产生新修订；旧确认不能放行新范围。
        self.control('confirm')  # 确认的是当前修订
        tweak = self.full_intent(technical={'title': '区域智能试验（二期）'})
        state, _ = self.wf.save_intent(tweak)  # 技术字段变化，确认再次失效
        with self.assertRaises(PartnerConfirmationRequired):
            self.wf.submit(tweak)
        self.control('confirm')  # 场景方针对新修订重新确认
        receipt = self.wf.submit(tweak)
        self.assertEqual(receipt.application, 'APP-001')  # 申请号保持稳定，未重建申请

    def test_03_dictionary_retired_enum_is_not_swapped_to_first_option(self):
        # 先以旧字典的 pilot 落一份草稿。
        old = self.full_intent(technical={'mode': 'pilot'})
        state, _ = self.wf.save_intent(old)
        self.assertEqual(self.site.state['technical']['mode'], 'pilot')
        # 门户更新字段字典：显示名称变化，pilot 被淘汰，新字典 trial/production。
        self.control('dictionary')
        state = self.portal.reload()
        self.assertEqual(state.dictionary, 2)
        self.assertEqual(state.mode_label, '运行类别')
        self.assertNotIn('pilot', state.mode_options)
        # RPA 拒绝把 pilot 悄悄换成第一个选项。
        with self.assertRaises(RetiredEnumError) as cm:
            self.wf.save_intent(old)
        self.assertEqual(cm.exception.value, 'pilot')
        # 页面上原 pilot 值未被 RPA 改写（不盲目选择）。
        self.assertNotEqual(self.site.state['technical']['mode'], 'trial')
        # 资料员按新字典显式改用 production 后可正常保存，字段身份仍是 mode。
        updated = self.full_intent(technical={'mode': 'production'})
        state, _ = self.wf.save_intent(updated)
        self.assertEqual(state.technical['mode'], 'production')

    def test_04_remove_scope_drops_only_its_own_fields_and_materials(self):
        intent = self.full_intent()
        self.wf.save_intent(intent)
        # 撤去院内 hospital：data_use 清空、data 材料撤下；notice/points 与 shared 保留。
        public_only = self.full_intent(
            technical={'scopes': ['public'], 'data_use': ''},
            materials=['shared', 'points'])
        state, _ = self.wf.save_intent(public_only)
        self.assertEqual(state.technical['scopes'], ['public'])
        self.assertEqual(state.technical['data_use'], '')
        self.assertEqual(state.technical['notice'], '点位周边告知')
        self.assertEqual(tuple(state.materials), ('shared', 'points'))
        # 页面义务文本同步只剩 shared,points。
        self.assertIn('shared,points', state.obligations_text)
        # 再撤去 public：共用 shared 也随之撤下，两个触发字段均为空。
        none = self.full_intent(
            technical={'scopes': [], 'data_use': '', 'notice': ''}, materials=[])
        state, _ = self.wf.save_intent(none)
        self.assertEqual(state.materials, ())
        self.assertNotIn('shared', state.obligations_text)

    def test_04b_reconcile_marks_stale_material_once(self):
        # 页面仍登记三类材料，但意图只保留 public：data 应只出现一条 stale 记录。
        intent = self.full_intent()
        self.wf.save_intent(intent)
        public_only = self.full_intent(
            technical={'scopes': ['public'], 'data_use': ''},
            materials=['shared', 'points'])
        state = self.portal.open()
        report = self.wf.reconcile(public_only, state)
        data_rows = [r for r in report.material_rows if r['material_id'] == 'data']
        self.assertEqual(len(data_rows), 1)
        self.assertEqual(data_rows[0]['status'], 'stale')
        self.assertFalse(report.ready_to_submit)

    def test_05_gateway_after_save_verified_no_duplicate_application(self):
        intent = self.full_intent()
        self.portal.open()
        self.control('lose_reply')  # 下次保存写入后返回 503
        state, attempts = self.wf.save_intent(intent)
        self.assertEqual(attempts[0].kind, 'uncertain')
        self.assertEqual(attempts[0].error_code, 'gateway_after_save')
        # 复核确认内容已落盘：不重建另一份申请，历史里只有一次 saved。
        self.assertEqual(state.technical['title'], '区域智能试验')
        self.assertEqual(
            [h for h in self.site.state['history'] if h['action'] == 'saved'].__len__(), 1)

    def test_06_navigation_timeout_after_save_treated_as_uncertain(self):
        intent = self.full_intent()
        self.portal.open()
        # 仅第一次 /draft 中断：模拟首次保存答复超时，随后网络恢复。
        calls = {'n': 0}

        def handler(route):
            calls['n'] += 1
            if calls['n'] == 1:
                return route.abort()
            return route.continue_()

        self.tab.route('**/draft', handler)
        self.portal.timeout_ms = 1500
        state, attempts = self.wf.save_intent(intent, reopen=False)
        self.assertEqual(attempts[0].kind, 'uncertain')
        self.assertEqual(attempts[-1].kind, 'saved')
        # 复核收敛后只有一次实际落盘，没有重建申请。
        saved = [h for h in self.site.state['history'] if h['action'] == 'saved']
        self.assertEqual(len(saved), 1)
        self.tab.unroute('**/draft')

    def test_07_targeted_correction_binds_original_application(self):
        # 先完成一次正式受理。
        intent = self.full_intent()
        self.wf.save_intent(intent)
        self.control('confirm')
        receipt = self.wf.submit(intent)
        self.assertEqual(receipt.application, 'APP-001')
        # 门户登记对 notice 的定向补正要求。
        self.control('correction', fields=['notice'])
        correction = Correction(
            application_reference='APP-001',
            fields=('notice',),
            technical=TechnicalFields.from_mapping({
                'title': '区域智能试验', 'scopes': ['hospital', 'public'],
                'mode': 'trial', 'data_use': '脱敏后院内试验',
                'notice': '点位周边补充告知（补正）'}),
        )
        result = self.wf.correct(correction)
        # 技术字段变化产生新修订，旧确认失效：明确等待场景方，不代确认。
        self.assertTrue(result['awaiting_partner_confirmation'])
        updated = self.full_intent(
            technical={'notice': '点位周边补充告知（补正）'})
        with self.assertRaises(PartnerConfirmationRequired):
            self.wf.submit(updated)
        # 未受影响的已确认内容继续保留。
        self.assertEqual(self.site.state['technical']['data_use'], '脱敏后院内试验')
        # 场景方针对新修订确认，补正提交成功并在历史标记 corrected。
        self.control('confirm')
        receipt2 = self.wf.submit(updated)
        self.assertEqual(receipt2.application, 'APP-001')
        self.assertEqual(receipt2.history_entry['action'], 'corrected')
        self.assertEqual(receipt2.history_entry['corrected_fields'], ['notice'])

    def test_08_materials_only_correction_keeps_confirmation(self):
        intent = self.full_intent()
        self.wf.save_intent(intent)
        self.control('confirm')
        self.wf.submit(intent)
        self.assertEqual(self.site.state['confirmed'], self.site.state['revision'])
        # 仅补一张点位表（材料变更，不触技术范围，门户保留确认修订）。
        # 先撤掉 points 制造“缺少点位表”的补正场景。
        reduced = self.full_intent(materials=['shared', 'data'])
        # 直接经页面只改材料（技术字段保持不变，不递增修订）。
        state = self.portal.open()
        self.portal.fill_materials(['shared', 'data'])
        self.portal.save_draft()
        self.assertEqual(self.site.state['confirmed'], self.site.state['revision'])
        correction = Correction(
            application_reference='APP-001', fields=(),
            technical=None, materials=('shared', 'data', 'points'))
        result = self.wf.correct(correction)
        self.assertFalse(result['awaiting_partner_confirmation'])
        self.assertEqual(result['receipt'].application, 'APP-001')
        self.assertEqual(tuple(self.site.state['materials']),
                         ('shared', 'data', 'points'))

    def test_09_unknown_application_correction_rejected(self):
        intent = self.full_intent()
        self.wf.save_intent(intent)
        correction = Correction(
            application_reference='APP-999', fields=('notice',),
            technical=TechnicalFields.from_mapping(
                {'title': 'x', 'scopes': ['public'], 'notice': 'y'}))
        with self.assertRaises(PortalError) as cm:
            self.wf.correct(correction)
        self.assertEqual(cm.exception.code, 'unknown_application')

    def test_10_incomplete_draft_savable_but_not_submittable(self):
        partial = Intent.from_mapping({
            'application_reference': 'co-create-alpha', 'actor': 'technical',
            'technical': {'title': '只有标题', 'scopes': ['hospital'], 'mode': 'trial'},
            'materials': []})
        state, attempts = self.wf.save_intent(partial)  # 不完整草稿允许逐次保存
        self.assertEqual(attempts[-1].kind, 'saved')
        with self.assertRaises(IncompleteDraft) as cm:
            self.wf.submit(partial)
        self.assertIn('data_use', cm.exception.missing_fields)
        self.assertIn('data', cm.exception.missing_materials)

    def test_11_reconcile_is_read_only(self):
        intent = self.full_intent()
        self.portal.open()
        before = json.dumps(self.site.state, sort_keys=True, ensure_ascii=False)
        self.wf.reconcile(intent)
        after = json.dumps(self.site.state, sort_keys=True, ensure_ascii=False)
        self.assertEqual(before, after)


class ClientBoundaryTest(unittest.TestCase):
    def test_client_never_calls_drill_control_endpoint(self):
        # RPA 代码不得出现演练控制端点，技术方不能借 __control 代确认。
        root = Path(__file__).resolve().parent.parent / 'client'
        for path in root.rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('__control', text, f'{path} 不得引用演练控制端点')
            self.assertNotIn("'confirm'", text)
