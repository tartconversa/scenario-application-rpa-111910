"""命令行入口：资料员本地驱动 Chromium 完成申请续填与提交。

示例：
  python -m client.cli import --request inputs/request.json --base http://127.0.0.1:8765
  python -m client.cli reconcile --request inputs/request.json
  python -m client.cli submit --request inputs/request.json
  python -m client.cli correct --correction inputs/correction.json
  python -m client.cli history
所有写操作都通过真实页面点击保存，证据写入 --evidence-dir。
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from client.model import Intent, Correction
from client.portal import PortalPage
from client.workflow import RpaWorkflow
from client.evidence import Evidence
from client.exceptions import RpaError, SubmissionBlocked, RetiredEnumError


def build_workflow(args):
    evidence = Evidence(
        directory=args.evidence_dir,
        application_reference=Path(args.request).stem if args.request else 'portal-session',
    )
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=not args.headed, args=['--no-sandbox'])
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    portal = PortalPage(page, args.base, evidence, timeout_ms=args.timeout_ms)
    workflow = RpaWorkflow(portal, evidence)
    return workflow, pw, browser, context, evidence


def teardown(pw, browser, context, evidence):
    evidence.persist()
    context.close()
    browser.close()
    pw.stop()


def load_intent(path):
    return Intent.load(path)


def cmd_import(args):
    intent = load_intent(args.request)
    wf, pw, browser, context, evidence = build_workflow(args)
    try:
        state, attempts = wf.save_intent(intent)
        report = wf.reconcile(intent, state)
        print(report.as_text())
        print(f"\n本次保存尝试 {len(attempts)} 次，证据目录：{evidence.directory}")
        return 0
    finally:
        teardown(pw, browser, context, evidence)


def cmd_reconcile(args):
    intent = load_intent(args.request)
    wf, pw, browser, context, evidence = build_workflow(args)
    try:
        state = wf.portal.open()
        report = wf.reconcile(intent, state)
        print(report.as_text())
        return 0 if report.ready_to_submit else 2
    finally:
        teardown(pw, browser, context, evidence)


def cmd_submit(args):
    intent = load_intent(args.request)
    wf, pw, browser, context, evidence = build_workflow(args)
    try:
        receipt = wf.submit(intent)
        print(f'正式提交成功，申请号 {receipt.application}，受理修订 {receipt.revision}')
        print('受理依据（历史记录）：' + json.dumps(receipt.history_entry, ensure_ascii=False))
        return 0
    finally:
        teardown(pw, browser, context, evidence)


def cmd_correct(args):
    correction = Correction.load(args.correction)
    args.request = args.correction
    wf, pw, browser, context, evidence = build_workflow(args)
    try:
        result = wf.correct(correction)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if result.get('awaiting_partner_confirmation'):
            return 3
        return 0
    finally:
        teardown(pw, browser, context, evidence)


def cmd_history(args):
    args.request = None
    wf, pw, browser, context, evidence = build_workflow(args)
    try:
        result = wf.query_history()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        teardown(pw, browser, context, evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description='共创申请门户 RPA 客户端（Chromium 页面驱动）')
    parser.add_argument('--base', default='http://127.0.0.1:8765', help='门户地址')
    parser.add_argument('--evidence-dir', default=None, help='证据留存目录（截图/快照/日志）')
    parser.add_argument('--headed', action='store_true', help='显示浏览器窗口（默认无头）')
    parser.add_argument('--timeout-ms', type=int, default=10000)
    sub = parser.add_subparsers(dest='command', required=True)

    p_import = sub.add_parser('import', help='导入本地申请意图并经页面保存草稿')
    p_import.add_argument('--request', required=True)
    p_import.set_defaults(func=cmd_import)

    p_rec = sub.add_parser('reconcile', help='页面续填前的差异核对（只读，不保存）')
    p_rec.add_argument('--request', required=True)
    p_rec.set_defaults(func=cmd_reconcile)

    p_sub = sub.add_parser('submit', help='保存并在条件满足时正式提交')
    p_sub.add_argument('--request', required=True)
    p_sub.set_defaults(func=cmd_submit)

    p_cor = sub.add_parser('correct', help='按原申请号登记定向补正')
    p_cor.add_argument('--correction', required=True)
    p_cor.set_defaults(func=cmd_correct)

    p_hist = sub.add_parser('history', help='查询草稿、受理与修订历史')
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RetiredEnumError as exc:
        print(f'[阻断] {exc}', file=sys.stderr)
        return 4
    except SubmissionBlocked as exc:
        print(f'[未提交] {exc}', file=sys.stderr)
        return 3
    except RpaError as exc:
        print(f'[RPA 错误] {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
