"""RPA 客户端异常类型。"""


class RpaError(Exception):
    """所有 RPA 客户端异常的基类。"""


class RetiredEnumError(RpaError):
    """输入使用了当前字段字典中已失效的枚举值。

    失效枚举不能被悄悄换成下拉框的第一个选项，必须交由资料员判断。
    """

    def __init__(self, field_id, value, available):
        self.field_id = field_id
        self.value = value
        self.available = list(available)
        super().__init__(
            f'字段 {field_id} 的枚举值 {value!r} 已在当前字段字典失效，'
            f'可选项为 {self.available}，未自动改写为第一个选项'
        )


class ConflictError(RpaError):
    """保存携带的页面修订已过期（门户返回 409 revision_conflict）。"""

    def __init__(self, current_revision):
        self.current_revision = current_revision
        super().__init__(f'页面修订冲突，门户当前修订为 {current_revision}')


class PortalError(RpaError):
    """门户返回的其它错误（4xx/5xx 或保存后答复丢失等）。"""

    def __init__(self, code, message='', detail=None):
        self.code = code
        self.detail = detail or {}
        super().__init__(f'门户返回 {code}: {message}'.rstrip(': '))


class SubmissionBlocked(RpaError):
    """正式提交不满足当前条件，基类。"""


class IncompleteDraft(SubmissionBlocked):
    """字段或材料不齐全，草稿可逐次保存但不能正式提交。"""

    def __init__(self, missing_fields=(), missing_materials=()):
        self.missing_fields = tuple(missing_fields)
        self.missing_materials = tuple(missing_materials)
        parts = []
        if self.missing_fields:
            parts.append('缺失字段 ' + ','.join(self.missing_fields))
        if self.missing_materials:
            parts.append('缺失材料 ' + ','.join(self.missing_materials))
        super().__init__('；'.join(parts) or '申请内容不完整')


class PartnerConfirmationRequired(SubmissionBlocked):
    """当前修订缺少场景方针对该修订的确认，技术方不能代确认。"""

    def __init__(self, revision, confirmed):
        self.revision = revision
        self.confirmed = confirmed
        super().__init__(
            f'当前修订 {revision} 与场景方确认修订 {confirmed} 不一致，'
            '需场景方在另一会话确认，技术方 RPA 不得代确认'
        )
