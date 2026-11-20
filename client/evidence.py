"""证据留存：记录实际页面保存、受理回执与每次浏览器动作。

RPA 不只生成离线文件，每份结论都要能追溯到真实页面动作：
- actions：有序动作日志（打开、填写、点击、答复）
- saves：每一次保存的修订、状态与页面原始答复
- receipts：正式提交返回的申请号与受理依据
- 截图与页面快照按运行目录落盘，供资料员复核。
"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import time


@dataclass
class SaveRecord:
    seq: int
    action: str                      # save_draft / submit
    page_revision: int               # 点击时页面携带的修订
    status: str                      # saved / conflict / error / uncertain / accepted / blocked
    response_revision: object = None
    response_text: str = ''
    error_code: str = ''
    note: str = ''
    at: float = field(default_factory=time.time)


@dataclass
class Receipt:
    application: str
    revision: int
    corrected_fields: list
    history_entry: dict
    at: float = field(default_factory=time.time)


class Evidence:
    def __init__(self, directory=None, application_reference=''):
        self.application_reference = application_reference
        self.actions = []
        self.saves = []
        self.receipts = []
        self.directory = Path(directory) if directory else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def log(self, action, detail=''):
        entry = {'at': round(time.time(), 3), 'action': action, 'detail': detail}
        self.actions.append(entry)
        return entry

    def record_save(self, **kwargs):
        record = SaveRecord(seq=len(self.saves) + 1, **kwargs)
        self.saves.append(asdict(record))
        self.persist()
        return record

    def record_receipt(self, receipt):
        self.receipts.append(asdict(receipt))
        self.persist()

    def capture(self, page, name):
        """保存页面截图与 HTML 快照；无运行目录时跳过。"""
        if not self.directory:
            return None
        stem = f'{len(self.actions):02d}_{name}'
        shot = self.directory / f'{stem}.png'
        html_path = self.directory / f'{stem}.html'
        try:
            page.screenshot(path=str(shot), full_page=True)
            html_path.write_text(page.content(), encoding='utf-8')
        except Exception as exc:  # 证据失败不应中断主流程，但要留痕
            self.log('evidence_capture_failed', f'{name}: {exc}')
            return None
        self.log('evidence_captured', str(shot))
        return {'screenshot': str(shot), 'snapshot': str(html_path)}

    def persist(self):
        if not self.directory:
            return
        payload = {
            'application_reference': self.application_reference,
            'actions': self.actions,
            'saves': self.saves,
            'receipts': self.receipts,
        }
        out = self.directory / 'evidence.json'
        tmp = out.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        tmp.replace(out)

    def as_mapping(self):
        return {
            'application_reference': self.application_reference,
            'actions': list(self.actions),
            'saves': list(self.saves),
            'receipts': list(self.receipts),
        }
