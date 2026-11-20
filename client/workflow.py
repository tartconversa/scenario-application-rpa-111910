"""RPA 编排：导入、续填、差异核对、提交与补正的完整工作流。

关键规则：
- 保存携带页面修订；409 时重新读页，保留场景方新内容后按最新修订重试，
  绝不新建另一份申请规避冲突。
- 保存技术字段只发技术方字段；场景方 owner/condition 只读观察。
- 答复丢失（503/超时）不认定未保存：先复核页面实际状态再决定下一步。
- 正式提交必须当前修订下字段材料齐全且场景方确认修订等于当前修订；
  确认针对具体修订，范围变化后旧确认不放行新范围。
- 补正绑定原申请号，只覆盖定向字段；范围变化导致旧确认失效时明确等待。
"""
from dataclasses import dataclass

from client.model import (
    Intent, Correction, TechnicalFields, required_materials, applicable_fields,
    reconcile_materials, TECHNICAL_FIELD_IDS,
)
from client.evidence import Receipt
from client.exceptions import (
    RetiredEnumError, ConflictError, PortalError, IncompleteDraft,
    PartnerConfirmationRequired,
)


@dataclass
class ReconcileReport:
    """差异核对结论：让资料员知道哪些已保存、哪些仍需另一方确认。"""

    page_revision: int
    confirmed_revision: int
    confirmation_current: bool
    field_rows: list
    material_rows: list
    partner: dict
    partner_changed: bool
    obligations: str
    dictionary: int
    mode_label: str
    ready_to_submit: bool
    blockers: list

    def as_text(self):
        lines = [
            f'页面修订 {self.page_revision}｜场景方确认修订 {self.confirmed_revision}'
            f'｜确认{"有效" if self.confirmation_current else "不适用，需场景方重新确认"}',
            f'字段字典 {self.dictionary}（mode 显示名称：{self.mode_label}）',
            '字段差异：',
        ]
        for row in self.field_rows:
            lines.append(
                f"  - {row['field_id']}（页面显示名 {row['label']}）："
                f"{row['status']} 页面={row['page']!r} 意图={row['intent']!r}"
                + (f" 说明：{row['note']}" if row['note'] else '')
            )
        lines.append('材料差异：')
        for row in self.material_rows:
            lines.append(f"  - {row['material_id']}：{row['status']}（{row['note']}）")
        lines.append(f'材料义务（页面实测）：{self.obligations}')
        lines.append(
            '场景方字段（只读）：'
            + '，'.join(f'{k}={v!r}' for k, v in self.partner.items())
            + ('（检测到另一会话已修改）' if self.partner_changed else '')
        )
        if self.ready_to_submit:
            lines.append('结论：满足当前提交条件。')
        else:
            lines.append('结论：暂不能正式提交，阻塞项：')
            for b in self.blockers:
                lines.append(f'  * {b}')
        return '\n'.join(lines)


class RpaWorkflow:
    def __init__(self, portal, evidence=None, max_conflict_retries=5):
        self.portal = portal
        self.evidence = evidence
        self.max_conflict_retries = max_conflict_retries
        self._last_partner = None

    # ---------- 差异核对 ----------
    def reconcile(self, intent, state=None):
        state = state or self.portal.read_state()
        target = intent.technical
        applied = applicable_fields(target.scopes)
        field_rows = []
        blockers = []
        for fid in TECHNICAL_FIELD_IDS:
            page_val = state.technical.get(fid, [] if fid == 'scopes' else '')
            intent_val = list(target.scopes) if fid == 'scopes' else getattr(target, fid)
            if fid == 'scopes':
                same = tuple(page_val) == tuple(intent_val)
            else:
                same = page_val == intent_val
            if fid not in applied and fid in ('data_use', 'notice'):
                status = 'not_applicable'
                note = '当前应用范围不触发该字段'
            elif same:
                status = 'saved'
                note = '页面已保存与意图一致'
            else:
                status = 'pending_fill'
                note = '页面与意图不一致，需保存'
                blockers.append(f'字段 {fid} 尚未保存为意图值')
            field_rows.append({
                'field_id': fid, 'label': state.field_labels.get(fid, fid),
                'status': status, 'page': page_val, 'intent': intent_val, 'note': note,
            })

        needed = required_materials(target.scopes)
        material_rows = []
        page_materials = set(state.materials)
        for mid in ('shared', 'data', 'points'):
            if mid not in needed:
                if mid in page_materials:
                    # 页面仍登记但当前范围已不需要：只记一条 stale，不与 not_required 重复。
                    status = 'stale'
                    note = '触发范围已撤去，该材料义务应撤下（不影响仍共用的材料）'
                    blockers.append(f'材料 {mid} 已不再被当前范围需要')
                else:
                    status = 'not_required'
                    note = '当前范围不产生该材料义务'
            elif mid in page_materials:
                status = 'saved'
                note = '义务材料已在页面登记'
            else:
                status = 'pending_material'
                note = '范围要求但页面未登记'
                blockers.append(f'材料 {mid} 未登记')
            material_rows.append({'material_id': mid, 'status': status, 'note': note})

        partner_changed = (
            self._last_partner is not None and state.partner != self._last_partner
        )
        missing_fields, missing_materials = intent.missing_for_submission()
        if missing_fields:
            blockers.append('必填字段为空：' + ','.join(missing_fields))
        if missing_materials:
            blockers.append('义务材料缺失：' + ','.join(missing_materials))
        confirmation_current = state.confirmation_current
        if not confirmation_current:
            blockers.append(
                f'场景方确认修订 {state.confirmed} 与当前修订 {state.revision} 不一致'
            )
        ready = not blockers
        report = ReconcileReport(
            page_revision=state.revision,
            confirmed_revision=state.confirmed,
            confirmation_current=confirmation_current,
            field_rows=field_rows,
            material_rows=material_rows,
            partner=dict(state.partner),
            partner_changed=partner_changed,
            obligations=state.obligations_text,
            dictionary=state.dictionary,
            mode_label=state.mode_label,
            ready_to_submit=ready,
            blockers=blockers,
        )
        self._last_partner = dict(state.partner)
        if self.evidence:
            self.evidence.log('reconcile', f'revision={state.revision} ready={ready}')
            self.evidence.persist()
        return report

    # ---------- 保存（含冲突与答复丢失处理） ----------
    def save_intent(self, intent, reopen=True):
        """把意图技术字段与材料经页面保存为草稿。

        冲突时重读页面（场景方新内容随页面自然保留），按最新修订重试；
        答复丢失时复核页面实际内容，已落盘则不重复构造申请，未落盘则同修订重试。
        reopen=False 时复用浏览器当前页（用于复现页面已打开后双方编辑相遇）。
        返回 (最终 PageState, 本次保存尝试记录列表)。
        """
        attempts = []
        state = self.portal.open() if reopen else self.portal.read_state()
        self._last_partner = dict(state.partner)
        conflicts = 0
        # 总尝试次数同时覆盖冲突重试与答复丢失重试，避免异常场景下死循环。
        for attempt in range(1, self.max_conflict_retries * 2 + 4):
            # 失效枚举在写入前拦截，绝不选第一个选项兜底。
            if intent.technical.mode not in state.mode_options:
                raise RetiredEnumError('mode', intent.technical.mode, state.mode_options)
            self.portal.fill_technical(intent.technical, state)
            materials = intent.target_materials()
            self.portal.fill_materials(materials)
            if self.evidence:
                self.evidence.capture(self.portal.page, f'before_save_{attempt}')
            outcome = self.portal.save_draft()
            attempts.append(outcome)

            if outcome.kind == 'saved':
                if self.evidence:
                    self.evidence.record_save(
                        action='save_draft', page_revision=state.revision,
                        status='saved', response_revision=outcome.revision,
                        response_text=outcome.raw_text,
                        note=f'页面确认保存修订 {outcome.revision}',
                    )
                return self.portal.reload(), attempts

            if outcome.kind == 'uncertain':
                # 503/超时：写入可能已完成。复核页面，不凭超时认定未保存。
                check = self.portal.verify_persisted(intent.technical, materials)
                note = '答复丢失后复核：' + (
                    f"内容已落盘（修订 {check['page_revision']}），无需重建申请"
                    if check['persisted'] else '页面未见目标内容，按当前修订重试'
                )
                if self.evidence:
                    self.evidence.record_save(
                        action='save_draft', page_revision=state.revision,
                        status='uncertain_confirmed' if check['persisted'] else 'uncertain_retry',
                        response_text=outcome.raw_text, error_code=outcome.error_code, note=note,
                    )
                state = check['state']
                if check['persisted']:
                    return state, attempts
                continue

            if outcome.kind == 'conflict':
                # 场景方在另一会话编辑会递增修订；重读即取得对方新内容并保留。
                conflicts += 1
                if conflicts > self.max_conflict_retries:
                    raise ConflictError(outcome.revision)
                note = (f'修订冲突（携带 {state.revision}，门户当前 '
                        f'{outcome.revision}）；重读页面保留场景方新内容后重试')
                if self.evidence:
                    self.evidence.record_save(
                        action='save_draft', page_revision=state.revision,
                        status='conflict', response_revision=outcome.revision,
                        response_text=outcome.raw_text,
                        error_code='revision_conflict', note=note,
                    )
                state = self.portal.reload()
                self._last_partner = dict(state.partner)
                continue

            # incomplete 等其它门户错误
            if self.evidence:
                self.evidence.record_save(
                    action='save_draft', page_revision=state.revision,
                    status='error', response_text=outcome.raw_text,
                    error_code=outcome.error_code,
                )
            raise PortalError(outcome.error_code, outcome.raw_text, outcome.detail)

        raise ConflictError(state.revision)

    # ---------- 正式提交 ----------
    def _page_matches_intent(self, state, intent):
        """页面技术字段与材料是否已与意图完全一致（一致则无需再保存）。"""
        t = intent.technical
        if tuple(state.technical.get('scopes', ())) != tuple(t.scopes):
            return False
        for fid in ('title', 'data_use', 'notice', 'mode'):
            if state.technical.get(fid, '') != getattr(t, fid):
                return False
        return tuple(state.materials) == tuple(intent.target_materials())

    def submit(self, intent):
        """提交前在当前页面做条件核对，再点击正式提交。

        门禁以门户为准；本地预检仅提前给出可解释的阻塞原因。
        提交前强制重读页面：场景方可能刚在另一会话完成确认，旧页面基线已过期。
        页面内容已与意图一致时不再保存，避免无变更保存产生新修订而使确认失效。
        """
        state = self.portal.reload()
        if not self._page_matches_intent(state, intent):
            # 仅在确有差异时才经页面保存；保存会产生新修订并使旧确认失效。
            state, _ = self.save_intent(intent, reopen=False)
            state = self.portal.reload()
        report = self.reconcile(intent, state)
        missing_fields, missing_materials = intent.missing_for_submission()
        if missing_fields or missing_materials:
            if self.evidence:
                self.evidence.record_save(
                    action='submit', page_revision=state.revision, status='blocked',
                    error_code='incomplete',
                    note='字段或材料不齐全，草稿可留存但不能正式提交',
                )
            raise IncompleteDraft(missing_fields, missing_materials)
        if not state.confirmation_current:
            if self.evidence:
                self.evidence.record_save(
                    action='submit', page_revision=state.revision, status='blocked',
                    error_code='partner_confirmation_required',
                    note='确认针对具体修订；范围或条件变化后旧确认不放行',
                )
            raise PartnerConfirmationRequired(state.revision, state.confirmed)

        if self.evidence:
            self.evidence.capture(self.portal.page, 'before_submit')
        outcome = self.portal.submit()
        if outcome.kind == 'accepted':
            history = self.portal.open_history()
            entry = next((h for h in reversed(history.get('history', []))
                          if h.get('application') == outcome.detail.get('application')), {})
            receipt = Receipt(
                application=outcome.detail['application'],
                revision=outcome.detail.get('revision'),
                corrected_fields=outcome.detail.get('correction', []),
                history_entry=entry,
            )
            if self.evidence:
                self.evidence.record_save(
                    action='submit', page_revision=state.revision, status='accepted',
                    response_revision=receipt.revision, response_text=outcome.raw_text,
                    note=f'门户返回申请号 {receipt.application}',
                )
                self.evidence.record_receipt(receipt)
            return receipt
        if outcome.kind == 'conflict':
            if self.evidence:
                self.evidence.record_save(
                    action='submit', page_revision=state.revision, status='conflict',
                    response_revision=outcome.revision, response_text=outcome.raw_text,
                    error_code='revision_conflict',
                )
            raise ConflictError(outcome.revision)
        if outcome.kind == 'uncertain':
            if self.evidence:
                self.evidence.record_save(
                    action='submit', page_revision=state.revision, status='uncertain',
                    response_text=outcome.raw_text, error_code=outcome.error_code,
                    note='提交答复丢失，以 /history 受理记录为准，不重复提交',
                )
            raise PortalError(outcome.error_code, '提交答复丢失，请经历史页核对受理依据',
                              outcome.detail)
        code = outcome.error_code
        if self.evidence:
            self.evidence.record_save(
                action='submit', page_revision=state.revision, status='blocked',
                response_text=outcome.raw_text, error_code=code,
            )
        if code == 'partner_confirmation_required':
            raise PartnerConfirmationRequired(state.revision, state.confirmed)
        if code == 'incomplete':
            raise IncompleteDraft()
        raise PortalError(code, outcome.raw_text, outcome.detail)

    # ---------- 定向补正 ----------
    def correct(self, correction):
        """针对原申请号的补正：只覆盖指定字段/材料，未受影响内容保留。

        范围变化会产生新修订并使旧确认失效，此时明确等待场景方重新确认，
        不替合作方确认。
        """
        state = self.portal.open()
        history = self.portal.open_history()
        known_apps = {h.get('application') for h in history.get('history', [])
                      if isinstance(h, dict)}
        if correction.application_reference not in known_apps:
            raise PortalError(
                'unknown_application',
                f'补正必须对应原申请号，门户历史中未见 {correction.application_reference}',
            )
        # 以页面当前技术字段为基底，仅覆盖补正指定字段，其余已确认内容继续保留。
        base = TechnicalFields.from_payload(state.technical)
        if correction.technical is not None:
            patch = correction.technical.to_payload()
            merged = base.to_payload()
            for fid in correction.fields:
                merged[fid] = patch[fid]
            new_tech = TechnicalFields.from_mapping(merged)
        else:
            new_tech = base
        if correction.materials is not None:
            # 撤范围时只撤触发材料；共用材料仍被另一范围需要则保留。
            keep, drop = reconcile_materials(
                state.materials, new_tech.scopes, correction.materials
            )
            wanted = list(keep)
            for m in correction.materials:
                if m in required_materials(new_tech.scopes) and m not in wanted:
                    wanted.append(m)
            new_materials = tuple(wanted)
            if self.evidence and drop:
                self.evidence.log('correction_drop_materials', ','.join(drop))
        else:
            new_materials = state.materials

        intent = Intent(
            application_reference=correction.application_reference,
            actor='technical', technical=new_tech, materials=new_materials,
        )
        tech_changed = new_tech.to_payload() != base.to_payload()
        state, attempts = self.save_intent(intent)
        if tech_changed:
            # 技术字段变化产生新修订，场景方旧确认不再适用：明确等待，不替合作方确认。
            # （仅材料变更不改变技术范围时，门户保留确认修订，可直接再提交。）
            if self.evidence:
                self.evidence.log(
                    'correction_wait_confirmation',
                    '补正改变技术字段，旧确认不适用，等待场景方确认新修订',
                )
            return {
                'application': correction.application_reference,
                'saved_revision': state.revision,
                'awaiting_partner_confirmation': True,
                'note': '技术字段变化使旧确认失效，需场景方针对新修订确认后再提交',
            }
        receipt = self.submit(intent)
        return {
            'application': receipt.application,
            'saved_revision': state.revision,
            'awaiting_partner_confirmation': False,
            'receipt': receipt,
        }

    # ---------- 提交经历查询 ----------
    def query_history(self):
        history = self.portal.open_history()
        entries = history.get('history', [])
        accepted = [h for h in entries if h.get('action') in ('accepted', 'corrected')]
        return {
            'application': history.get('receipt'),
            'current_revision': history.get('revision'),
            'confirmed_revision': history.get('confirmed'),
            'dictionary': history.get('dictionary'),
            'materials': history.get('materials', []),
            'corrections_open': history.get('correction', []),
            'timeline': entries,
            'acceptances': accepted,
            'raw': history,
        }
