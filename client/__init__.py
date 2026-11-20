"""共创申请 RPA 客户端：经 Chromium 续填合成门户，不生成离线申请文件。"""
from client.exceptions import (
    RpaError, RetiredEnumError, ConflictError, PortalError,
    SubmissionBlocked, IncompleteDraft, PartnerConfirmationRequired,
)
from client.model import Intent, Correction, TechnicalFields, required_materials, FIELD_IDS
from client.evidence import Evidence
from client.portal import PortalPage, PageState, SaveOutcome
from client.workflow import RpaWorkflow, ReconcileReport

__all__ = [
    'RpaError', 'RetiredEnumError', 'ConflictError', 'PortalError',
    'SubmissionBlocked', 'IncompleteDraft', 'PartnerConfirmationRequired',
    'Intent', 'Correction', 'TechnicalFields', 'required_materials', 'FIELD_IDS',
    'Evidence', 'PortalPage', 'PageState', 'SaveOutcome',
    'RpaWorkflow', 'ReconcileReport',
]
