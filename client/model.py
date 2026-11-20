"""领域模型：字段身份、条件材料义务、申请意图与完整性规则。

字段身份以稳定标识（input id）为准，门户字段字典更新只改变显示名称，
不改变字段身份；因此 RPA 全程使用字段标识定位，不按显示名称定位。
"""
from dataclasses import dataclass
from pathlib import Path
import json

# 技术方可写字段的稳定字段标识。显示名称（“试验类型”→“运行类别”）变化不影响身份。
TECHNICAL_FIELD_IDS = ('title', 'scopes', 'data_use', 'notice', 'mode')
FIELD_IDS = TECHNICAL_FIELD_IDS
# 场景方字段：技术方只能观察，任何保存负载都不得包含。
PARTNER_FIELD_IDS = ('owner', 'condition')
# 应用范围标识与各自触发的字段/材料。
SCOPE_IDS = ('hospital', 'public')
SCOPE_TRIGGERED_FIELDS = {'hospital': ('data_use',), 'public': ('notice',)}
SCOPE_TRIGGERED_MATERIALS = {'hospital': ('data',), 'public': ('points',)}
# 只要存在任一应用范围就需要的共用材料。
SHARED_MATERIAL = 'shared'
MATERIAL_IDS = ('shared', 'data', 'points')


def required_materials(scopes):
    """按当前应用范围计算材料义务。

    院内 hospital 触发 data；公共 public 触发 points；
    任一范围存在即需要共用材料 shared。两个范围同时覆盖时两边义务取并集。
    """
    scopes = tuple(scopes)
    needed = set()
    if scopes:
        needed.add(SHARED_MATERIAL)
    for scope in scopes:
        needed.update(SCOPE_TRIGGERED_MATERIALS[scope])
    return needed


def applicable_fields(scopes):
    """当前范围下适用的技术字段标识集合。"""
    scopes = tuple(scopes)
    fields = {'title', 'scopes', 'mode'}
    for scope in scopes:
        fields.update(SCOPE_TRIGGERED_FIELDS[scope])
    return fields


@dataclass(frozen=True)
class TechnicalFields:
    """门户技术方字段的一次取值，键名即稳定字段标识。"""

    title: str = ''
    scopes: tuple = ()
    data_use: str = ''
    notice: str = ''
    mode: str = 'trial'

    @classmethod
    def from_mapping(cls, data):
        unknown = set(data) - set(TECHNICAL_FIELD_IDS)
        if unknown:
            raise ValueError(f'未知技术字段标识: {sorted(unknown)}')
        scopes = tuple(data.get('scopes', ()))
        bad = [s for s in scopes if s not in SCOPE_IDS]
        if bad:
            raise ValueError(f'未知应用范围标识: {bad}')
        return cls(
            title=str(data.get('title', '')),
            scopes=scopes,
            data_use=str(data.get('data_use', '')),
            notice=str(data.get('notice', '')),
            mode=str(data.get('mode', 'trial')),
        )

    def to_payload(self):
        """转为门户保存负载（只含技术方可写字段）。"""
        return {
            'title': self.title,
            'scopes': list(self.scopes),
            'data_use': self.data_use,
            'notice': self.notice,
            'mode': self.mode,
        }

    @classmethod
    def from_payload(cls, payload):
        return cls.from_mapping(payload)

    def with_scopes_removed(self, removed):
        """撤去应用范围：连带清空仅由该范围触发的字段值。

        共用字段与另一范围仍触发的字段保留。
        """
        removed = set(removed)
        kept = [s for s in self.scopes if s not in removed]
        data = self.to_payload()
        data['scopes'] = kept
        remaining = applicable_fields(kept)
        for fid in TECHNICAL_FIELD_IDS:
            if fid not in remaining and fid not in ('title', 'scopes', 'mode'):
                data[fid] = ''
        return TechnicalFields.from_mapping(data)


@dataclass(frozen=True)
class Intent:
    """本地申请意图（inputs/request.json 的合成材料读取结果）。"""

    application_reference: str
    actor: str
    technical: TechnicalFields
    materials: tuple

    @classmethod
    def load(cls, source):
        if isinstance(source, (str, Path)):
            # -I 运行时也显式指定 utf-8，避免依赖平台编码。
            raw = json.loads(Path(source).read_text(encoding='utf-8'))
        else:
            raw = json.loads(json.dumps(source))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError('申请意图必须是 JSON 对象')
        ref = raw.get('application_reference')
        if not ref:
            raise ValueError('申请意图缺少 application_reference')
        actor = raw.get('actor')
        # 页面 / 身份固定为技术方资料员；场景方意图不能由本 RPA 代填。
        if actor != 'technical':
            raise ValueError(
                f'本 RPA 仅接受技术方意图（actor=technical），收到 actor={actor!r}'
            )
        if 'technical' not in raw or not isinstance(raw['technical'], dict):
            raise ValueError('申请意图缺少 technical 对象')
        technical = TechnicalFields.from_mapping(raw['technical'])
        materials = tuple(raw.get('materials', ()))
        unknown = [m for m in materials if m not in MATERIAL_IDS]
        if unknown:
            raise ValueError(f'未知材料标识: {unknown}')
        return cls(application_reference=str(ref), actor=actor,
                   technical=technical, materials=materials)

    def target_materials(self):
        """意图材料与当前范围义务的交集：不提交义务之外的材料，也不丢义务材料。"""
        needed = required_materials(self.technical.scopes)
        target = [m for m in self.materials if m in needed]
        for m in sorted(needed):
            if m not in target:
                target.append(m)
        return tuple(target)

    def missing_for_submission(self):
        """返回 (缺失字段标识, 缺失材料标识)，空元组表示当前范围下内容齐全。"""
        t = self.technical
        missing_fields = []
        if not t.title:
            missing_fields.append('title')
        if not t.scopes:
            missing_fields.append('scopes')
        if 'hospital' in t.scopes and not t.data_use:
            missing_fields.append('data_use')
        if 'public' in t.scopes and not t.notice:
            missing_fields.append('notice')
        needed = required_materials(t.scopes)
        missing_materials = sorted(needed - set(self.materials))
        return tuple(missing_fields), tuple(missing_materials)


@dataclass(frozen=True)
class Correction:
    """针对原申请号的定向补正意图：只覆盖指定字段/材料，其余已确认内容保留。"""

    application_reference: str
    fields: tuple = ()
    technical: object = None
    materials: object = None

    @classmethod
    def load(cls, source):
        if isinstance(source, (str, Path)):
            raw = json.loads(Path(source).read_text(encoding='utf-8'))
        else:
            raw = json.loads(json.dumps(source))
        ref = raw.get('application_reference')
        if not ref:
            raise ValueError('补正意图缺少 application_reference（必须对应原申请号）')
        fields = tuple(raw.get('fields', ()))
        unknown = [f for f in fields if f not in TECHNICAL_FIELD_IDS]
        if unknown:
            raise ValueError(f'补正字段含未知字段标识: {unknown}')
        technical = (TechnicalFields.from_mapping(raw['technical'])
                     if raw.get('technical') is not None else None)
        materials = raw.get('materials')
        if materials is not None:
            materials = tuple(materials)
            bad = [m for m in materials if m not in MATERIAL_IDS]
            if bad:
                raise ValueError(f'补正材料含未知标识: {bad}')
        return cls(str(ref), fields, technical, materials)


def reconcile_materials(current_materials, scopes, intent_materials):
    """撤去范围时的材料差异核对。

    只撤去被撤范围触发、且不再被其它范围需要的材料义务；
    共用材料 shared 仍供另一范围使用时保留。
    返回 (建议保留材料有序元组, 应撤去材料元组)。
    """
    needed = required_materials(scopes)
    current = tuple(current_materials)
    keep = [m for m in current if m in needed]
    drop = tuple(m for m in current if m not in needed)
    # 意图中声明、当前义务需要、页面尚缺的材料补入。
    for m in intent_materials:
        if m in needed and m not in keep:
            keep.append(m)
    return tuple(keep), drop
