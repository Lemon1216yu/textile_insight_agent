"""Permission-filtered Chinese BM25 and reciprocal rank fusion."""
import re,logging
from functools import lru_cache
import jieba,bm25s
jieba.setLogLevel(logging.ERROR)

def tokens(text):
    words=[]
    for word in jieba.lcut(text.lower()):
        if re.search(r'[\w\u4e00-\u9fff]',word):
            words.append(word)
            if '_' in word:words.extend(word.split('_'))
    return words or ['empty']

@lru_cache(maxsize=32)
def index(texts):
    model=bm25s.BM25()
    model.index(bm25s.tokenize([' '.join(tokens(t)) for t in texts],lower=False,stopwords=None,token_pattern=r'(?u)\b\w+\b',show_progress=False),show_progress=False)
    return model

def lexical_search(question,docs,limit):
    if not docs:return []
    model=index(tuple(d['text'] for d in docs))
    query=bm25s.tokenize([' '.join(tokens(question))],lower=False,stopwords=None,token_pattern=r'(?u)\b\w+\b',show_progress=False)
    ids,scores=model.retrieve(query,k=min(limit,len(docs)),show_progress=False)
    return [{**docs[int(i)],'score':float(score),'source':'bm25'} for i,score in zip(ids[0],scores[0]) if score>0]

def identity(doc):return (doc['kind'],doc.get('table_name',''),doc['name'])

def rrf(*rankings,limit=10,k=60):
    scores={};items={};sources={}
    for source,ranking in zip(['vector','bm25'],rankings):
        for rank,item in enumerate(ranking,1):
            key=identity(item);items[key]=item
            scores[key]=scores.get(key,0)+1/(k+rank)
            sources.setdefault(key,[]).append(source)
    ordered=sorted(scores,key=lambda key:(-scores[key],key))[:limit]
    return [{**items[key],'score':round(scores[key],6),'sources':sources[key]} for key in ordered]
