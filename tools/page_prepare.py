"""Gather a draft's inputs: article.txt, links.txt (video titles, Telegram text, bulletin text)
and docs/ (the full linked documents and guide sections).

usage: page_prepare.py CRUNCH_DIR ARTICLE_ID [ARTICLE_ID ...]   (reads build/solutions/data.json)
"""
import json,os,re,sys,time,html,subprocess,tempfile,urllib.request,urllib.parse
from common import ROOT
import solutions
from common import UA
C=sys.argv[1];ids=sys.argv[2:]
d=json.load(open(ROOT+'/build/solutions/data.json',encoding='utf8'))
known={x['id']:x['title'] for x in d['docs']};arts={a['id']:a for a in d['articles']}
def get(u,t=20):
    return urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA}),timeout=t).read()
def safe(s):return re.sub(r'[^\wء-ي-]+','_',s)[:50]
def note(u):
    h=urllib.parse.urlparse(u).netloc.lower().replace('www.','')
    try:
        if 'youtu' in h:
            j=json.loads(get('https://www.youtube.com/oembed?format=json&url='+urllib.parse.quote(u,safe='')));time.sleep(.15)
            return f"YouTube video: {j['title']} (channel: {j['author_name']})"
        if h=='t.me':
            m=re.search(r't\.me/(?:s/)?([^/?]+)/(\d+)',u)
            if m:
                t=get(f'https://t.me/{m.group(1)}/{m.group(2)}?embed=1&mode=tme').decode('utf8','ignore');time.sleep(.3)
                x=re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',t,re.S)
                if x:return 'Telegram post: '+re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',x.group(1)))).strip()[:500]
            return 'Telegram post (no readable text)'
        if u.lower().endswith('.pdf') and 'nhtsa' in h:
            with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
                f.write(get(u,40));f.flush()
                t=subprocess.run(['pdftotext','-l','2',f.name,'-'],capture_output=True,text=True,timeout=40).stdout
            return 'Mazda service bulletin, start of text: '+re.sub(r'\s+',' ',t)[:1800]
    except Exception as e:return f'({h}; could not read)'
    return h
for aid in ids:
    a=arts[aid];O=f'{C}/{aid}';os.makedirs(O+'/docs',exist_ok=True)
    body,n=solutions.article_text(a)
    open(O+'/article.txt','w',encoding='utf8').write(f"TITLE: {a['title']}\n\n{body}\n")
    links=solutions.article_links(a);lines=[];seen={};docs=set();navs=set()
    for i,r in enumerate(links,1):
        u=r['u'];nav=r.get('nav')
        if nav and nav.get('a') in arts:
            navs.add(nav['a']);info=f"section of this guide: {arts[nav['a']]['title']}"
        else:
            m=re.search(r'/document/d/([\w-]+)',u)
            if m and m.group(1) in known:
                docs.add(m.group(1));info=f"community document: {known[m.group(1)]}"
            else:
                if u not in seen:seen[u]=note(u)
                info=seen[u]
        lines.append(f"L{i} [{r['t'].strip()}] {info}")
    open(O+'/links.txt','w',encoding='utf8').write('\n'.join(lines)+'\n')
    size=0
    for g in docs:
        bl=solutions.load_doc(g);t='\n'.join(('#'*b['h']+' ' if b['h'] else '')+b['t'] for b in bl if b['t'].strip())
        open(f"{O}/docs/doc_{safe(known[g])}.txt",'w',encoding='utf8').write(f"DOCUMENT: {known[g]}\n\n{t}\n");size+=len(t)
    for x in navs:
        if x==aid:continue
        t,_=solutions.article_text(arts[x]);t=re.sub(r'\[L\d+:([^\]]*)\]',r'\1',t)
        open(f"{O}/docs/guide_{safe(arts[x]['title'])}.txt",'w',encoding='utf8').write(f"GUIDE SECTION: {arts[x]['title']}\n\n{t}\n");size+=len(t)
    print(aid,a['title'],'| links',n,'| docs',len(docs),'guide sections',len(navs-{aid}),'| doc chars',size,'| noted',len(seen))
