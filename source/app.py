"""双方分权、修订确认及条件材料的合成申请门户。"""
from source.common import *

class Site(Provider):
    def initial(self):return {'revision':1,'dictionary':1,'technical':{'scopes':[],'title':'','data_use':'','notice':'','mode':'trial'},'scenario':{'owner':'场景单位甲','condition':'白天试验'},'confirmed':0,'materials':[],'receipt':None,'history':[],'lose_reply':False,'correction':[]}
    def event(self,d):
        e=d['event']
        if e=='scenario_edit':self.state['scenario']['condition']=d.get('condition','夜间试验');self.state['revision']+=1
        elif e=='confirm':self.state['confirmed']=self.state['revision']
        elif e=='dictionary':self.state['dictionary']+=1
        elif e=='correction':self.state['correction']=d.get('fields',['notice'])
        elif e=='lose_reply':self.state['lose_reply']=True
        else:return Reply({'error':'unknown_event'},400)
        return {'ok':True}
    def get(self,p,q,h):
        if p=='/':
            s=self.state;t=s['technical'];v=s['revision']
            body='<p id="revision">修订 '+str(v)+'</p><pre id="partner">'+escaped(dump(s['scenario']))+'</pre><p id="confirmation">场景方确认修订 '+str(s['confirmed'])+'</p><p>当前身份：技术方资料员</p><label>项目<input id="title" value="'+escaped(t['title'])+'"></label>'
            for x,label in [('hospital','院内应用'),('public','公共场所')]:body+='<label><input class="scope" type="checkbox" value="'+x+'" '+('checked' if x in t['scopes'] else '')+'>'+label+'</label>'
            body+='''<div id="hospital"><label>数据用途<input id="data_use"></label><p>责任单位见场景方字段</p></div><div id="public"><label>采集告知<input id="notice"></label></div><p id="obligations"></p><label>已备材料（逗号分隔）<input id="materials"></label><button id="save">保存草稿</button><button id="submit">正式提交</button><pre id="result"></pre><a href="/history">申请历史</a>'''
            modes=['trial','pilot'] if s['dictionary']==1 else ['trial','production']
            body+='<label>'+('试验类型' if s['dictionary']==1 else '运行类别')+'<select id="mode">'+''.join('<option '+('selected' if m==t['mode'] else '')+'>'+m+'</option>' for m in modes)+'</select></label><p id="dictionary">字段字典 '+str(s['dictionary'])+'</p>'
            script='const baseline='+str(v)+';document.querySelector("#data_use").value='+dump(t['data_use'])+';document.querySelector("#notice").value='+dump(t['notice'])+';document.querySelector("#materials").value='+dump(','.join(s['materials']))+';'+'''
function scopes(){return Array.from(document.querySelectorAll('.scope:checked'),x=>x.value)}
function change(){let a=scopes();document.querySelector('#hospital').hidden=!a.includes('hospital');document.querySelector('#public').hidden=!a.includes('public');document.querySelector('#obligations').textContent='材料义务：'+[...(a.length?['shared']:[]),...(a.includes('hospital')?['data']:[]),...(a.includes('public')?['points']:[])].join(',');}
document.querySelectorAll('.scope').forEach(x=>x.onchange=change);change();
async function act(path){let data={revision:baseline,technical:{title:document.querySelector('#title').value,scopes:scopes(),data_use:document.querySelector('#data_use').value,notice:document.querySelector('#notice').value,mode:document.querySelector('#mode').value},materials:document.querySelector('#materials').value.split(',').filter(Boolean)};let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});document.querySelector('#result').textContent=await r.text();}
document.querySelector('#save').onclick=()=>act('/draft');document.querySelector('#submit').onclick=()=>act('/submit');'''
            return web(page('共创申请门户',body,script))
        if p=='/history':return web(page('申请受理历史','<pre id="history">'+escaped(dump(self.state))+'</pre>'))
        return super().get(p,q,h)
    def post(self,p,d,h):
        s=self.state
        if p=='/draft':
            if d['revision']!=s['revision']:return Reply({'error':'revision_conflict','current':s['revision']},409)
            if set(d['technical'])-{'title','scopes','data_use','notice','mode'}:return Reply({'error':'ownership'},403)
            if d['technical']['mode'] not in (['trial','pilot'] if s['dictionary']==1 else ['trial','production']):return Reply({'error':'retired_enum'},422)
            changed=d['technical']!=s['technical'];s['technical']=d['technical'];s['materials']=d['materials']
            if changed:s['revision']+=1
            s['history'].append({'action':'saved','revision':s['revision']})
            if s['lose_reply']:s['lose_reply']=False;return Reply({'error':'gateway_after_save'},503)
            return {'saved_revision':s['revision']}
        if p=='/submit':
            if d['revision']!=s['revision']:return Reply({'error':'revision_conflict'},409)
            t=s['technical'];a=t['scopes'];needed=({'shared'} if a else set())|({'data'} if 'hospital' in a else set())|({'points'} if 'public' in a else set())
            if not t['title'] or not a or not needed<=set(s['materials']) or ('hospital' in a and not t['data_use']) or ('public' in a and not t['notice']):return Reply({'error':'incomplete'},422)
            if s['confirmed']!=s['revision']:return Reply({'error':'partner_confirmation_required'},409)
            s['receipt']=s['receipt'] or 'APP-001';s['history'].append({'action':'accepted','application':s['receipt'],'revision':s['revision']});return {'application':s['receipt'],'revision':s['revision'],'correction':s['correction']}
        return super().post(p,d,h)

if __name__=='__main__':main(Site)
