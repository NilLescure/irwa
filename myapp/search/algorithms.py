import math
from collections import defaultdict

from myapp.search.objects import Document

import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize

try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab")

try:
    nltk.data.find("corpora/stopwords")
except LookupError:
    nltk.download("stopwords")

# Our tokenization function
EN_STOP_WORDS = set(stopwords.words("english"))
STEMMER = PorterStemmer()
def preproces_text(text):
    if not isinstance(text, str):
        return []
    text = text.lower()
    tokens = word_tokenize(text)
    tokens = [t for t in tokens if t.isalpha()]
    tokens = [t for t in tokens if t not in EN_STOP_WORDS]
    tokens = [STEMMER.stem(t) for t in tokens]
    return tokens

# We apply it to all the search engine
def _tokenize(text):
    return preproces_text(text)


# ---------------------------------------------------------------------
# Camps del Document i pesos per camp
# ---------------------------------------------------------------------

def _doc_fields(doc):
    """
    Retorna un diccionari camp -> text per als camps que volem indexar.
    """
    fields = {}

    # Camps textuals simples
    for field_name in (
        "title",
        "description",
        "brand",
        "category",
        "sub_category",
        "seller",
    ):
        value = getattr(doc, field_name, None)
        if value:
            fields[field_name] = str(value)

    # product_details: dict {clau: valor} → el considerem com un sol camp
    if getattr(doc, "product_details", None):
        values = []
        for v in doc.product_details.values():
            if v:
                values.append(str(v))
        if values:
            fields["product_details"] = " ".join(values)

    return fields


# Wieghts for the fields
field_weights = {
    "title": 0.9,
    "brand": 0.25,
    "category": 0.25,
    "sub_category": 0.125,
    "description": 0.125,
    "product_details": 0.25,
    "seller": 0.1,
}

# Function to create all the needed indexes at the start of the web
def build_indexes(corpus):
    # term -> pid -> [positions]
    index = defaultdict(lambda: defaultdict(list))
    # term -> pid -> {fields}
    field_index = defaultdict(lambda: defaultdict(set))
    # pid -> doc_lenght
    doc_length = {}

    for pid, doc in corpus.items():
        fields = _doc_fields(doc)

        pos = 0
        for field_name, text in fields.items():
            terms = _tokenize(text)
            for term in terms:
                # Positions of the term at the doc
                index[term][pid].append(pos)
                # Which fields appers the term
                field_index[term][pid].add(field_name)
                pos += 1
        if pos > 0:
            doc_length[pid] = pos
    if not doc_length:
        return {}, {}, {}, {}, 0.0

    N = len(doc_length)
    avgdl = sum(doc_length.values()) / float(N)
    # IDF
    idf = {}
    for term, postings in index.items():
        df = len(postings)
        if df > 0:
            idf[term] = math.log(N / df)
        else:
            idf[term] = 0.0
    return index, field_index, idf, doc_length, avgdl

# Our ranking algorithm
def rank_documents_ours(terms,docs,index,field_index,idf,doc_length,avgdl,k1=1.2,b=0.75,):
    if not docs or not doc_length:
        return [], []
    docs_set = set(docs)
    doc_scores = defaultdict(float)
    for term in terms:
        postings_for_term = index.get(term)
        if not postings_for_term:
            continue
        term_idf = idf.get(term, 0.0)
        if term_idf == 0.0:
            continue
        term_field_map = field_index.get(term, {})
        for pid in docs_set:
            positions = postings_for_term.get(pid)
            if not positions:
                continue
            tf_td = len(positions)
            Ld = doc_length.get(pid, 0)
            if Ld == 0:
                continue
            denom = k1 * ((1.0 - b) + b * (Ld / avgdl)) + tf_td
            score = term_idf * ((k1 + 1.0) * tf_td) / denom
            fields_for_doc = term_field_map.get(pid, set())
            if fields_for_doc:
                field_coeff = sum(field_weights.get(f, 0.0) for f in fields_for_doc)
            else:
                field_coeff = 0.0
            score *= field_coeff
            doc_scores[pid] += score

    doc_scores_list = [[score, pid] for pid, score in doc_scores.items()]
    doc_scores_list.sort(reverse=True, key=lambda x: x[0])
    result_docs = [x[1] for x in doc_scores_list]
    return result_docs, doc_scores_list

# We do the search
def search_in_corpus(query,search_id,corpus,index,field_index,idf,doc_length,avgdl,):
    if not query or not corpus:
        return []
    terms = _tokenize(query)
    if not terms:
        return []
    # 1) intersecció de docs que contenen tots els termes
    candidate_docs = None
    for term in terms:
        postings = index.get(term)
        if not postings:
            continue
        docs_for_term = set(postings.keys())
        if candidate_docs is None:
            candidate_docs = docs_for_term
        else:
            candidate_docs &= docs_for_term

    # 2) si intersecció buida, fem unió
    if not candidate_docs:
        candidate_docs = set()
        for term in terms:
            postings = index.get(term)
            if postings:
                candidate_docs.update(postings.keys())

    if not candidate_docs:
        return []

    candidate_docs_list = list(candidate_docs)
    ranked_pids, _scores = rank_documents_ours(terms,candidate_docs_list,index,field_index,idf,doc_length,avgdl,)

    if not ranked_pids:
        return []

    results = []
    for pid in ranked_pids:
        orig_doc = corpus[pid]

        data = orig_doc.model_dump()
        data["url"] = f"doc_details?pid={orig_doc.pid}&search_id={search_id}"

        doc_copy = Document(**data)
        results.append(doc_copy)
    return results
