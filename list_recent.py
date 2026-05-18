import json
with open('prd.json','r',encoding='utf-8') as f:
    d=json.load(f)
stories=[s for s in d.get('stories',[]) if s.get('passes') is True and s.get('_passedCommit')]
stories.sort(key=lambda s:s.get('_passedCommit',''),reverse=True)
for s in stories[:14]:
    print(s.get('id'),'|',(s.get('_passedCommit') or '')[:10],'|',s.get('title',''))
