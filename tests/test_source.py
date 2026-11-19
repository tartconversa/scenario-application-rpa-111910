from playwright.sync_api import expect
from tests.support import SourceTest

class ApplicationTest(SourceTest):
    def test_condition_owner_revision_and_receipt(self):
        p=self.browser();p.goto(self.base);p.fill('#title','协作项目');p.check('.scope[value="hospital"]');p.check('.scope[value="public"]');expect(p.locator('#obligations')).to_have_text('材料义务：shared,data,points')
        p.fill('#data_use','脱敏试验');p.fill('#notice','已告知');p.fill('#materials','shared,data,points')
        self.control('scenario_edit');p.click('#save');expect(p.locator('#result')).to_contain_text('revision_conflict');p.reload();expect(p.locator('#partner')).to_contain_text('夜间试验')
        p.fill('#title','协作项目');p.check('.scope[value="hospital"]');p.check('.scope[value="public"]');p.fill('#data_use','脱敏试验');p.fill('#notice','已告知');p.fill('#materials','shared,data,points');self.control('lose_reply');p.click('#save');expect(p.locator('#result')).to_contain_text('gateway_after_save');p.reload()
        p.click('#submit');expect(p.locator('#result')).to_contain_text('partner_confirmation_required');self.control('confirm');p.click('#submit');expect(p.locator('#result')).to_contain_text('APP-001')
        p.uncheck('.scope[value="hospital"]');expect(p.locator('#obligations')).to_have_text('材料义务：shared,points')
