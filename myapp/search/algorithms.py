"""def search_in_corpus(query):
    # 1. create create_tfidf_index
    def create_index_tfidf(dataframe, clean_df, columns, num_documents):
        index = defaultdict(list)
        tf = defaultdict(list)
        df = defaultdict(int)
        title_index = defaultdict(str)
        idf = defaultdict(float)

        for index_val, row in dataframe.iterrows():
            page_id = row['pid']
            terms = []
            for col in columns:
                val = row[col]
                trobat = re.findall(r"'([^']+)'", val)
                terms.extend(trobat)

            title = row['title']
            title = clean_df.loc[clean_df['pid'] == page_id, 'title'].values[0]
            title_index[page_id] = title

            current_page_index = {}

            for position, term in enumerate(terms):
                try:
                    current_page_index[term][1].append(position)
                except:
                    current_page_index[term] = [page_id, array('I', [position])]

            norm = 0
            for term, posting in current_page_index.items():
                norm += len(posting[1]) ** 2
            norm = math.sqrt(norm)

            for term, posting in current_page_index.items():
                tf[term].append(np.round(len(posting[1]) / norm, 4))
                df[term] += 1

            for term_page, posting_page in current_page_index.items():
                index[term_page].append(posting_page)

        for term in df:
            idf[term] = np.round(np.log(float(num_documents / df[term])), 4)

        return index, tf, df, idf, title_index
    indexing_columns = ['title', 'description', 'brand', 'category', 'sub_category', 'product_details', 'seller']
    index, tf, df, idf, title_index = create_index_tfidf(processed_df, clean_df, indexing_columns, len(processed_df))


    # 2. apply ranking

    return """
# algorithms.py
# myapp/search/algorithms.py

import math
import re
from collections import defaultdict
from typing import Dict, List

from myapp.search.objects import Document


# --- Helpers ---------------------------------------------------------

_token_re = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    """
    Tokenitza: passa a minúscules i es queda amb paraules alfanumèriques.
    """
    if not isinstance(text, str):
        return []
    return _token_re.findall(text.lower())


def _doc_text(doc: Document) -> str:
    """
    Construeix el text que farem servir per indexar cada document,
    combinant els mateixos camps que es fan servir al Part 3:
    title, description, brand, category, sub_category, product_details, seller.
    """
    parts: List[str] = []

    for field_name in ("title", "description", "brand",
                       "category", "sub_category", "seller"):
        value = getattr(doc, field_name, None)
        if value:
            parts.append(str(value))

    if doc.product_details:
        # product_details és un dict {clau: valor}
        for v in doc.product_details.values():
            if v:
                parts.append(str(v))

    return " ".join(parts)


# --- BM25 principal --------------------------------------------------


def search_in_corpus(query: str,
                     search_id: str,
                     corpus: Dict[str, Document],) -> List[Document]:
    """
    Cerca la `query` dins el `corpus` aplicant BM25.

    - Construeix un índex invertit i longitud dels documents.
    - Calcula IDF i puntuacions BM25.
    - Retorna una llista de `Document` ordenats (no s'afegeix cap camp nou al Document).

    Els `Document` retornats tenen el camp `url` apuntant a la vista interna
    de detalls: /doc_details?pid=...&search_id=...
    """

    # 0. Casos trivials
    if not query or not corpus:
        return []

    # 1. Indexació: terme -> {pid -> tf}, i longituds dels docs
    index: Dict[str, Dict[str, int]] = defaultdict(dict)
    doc_lengths: Dict[str, int] = {}

    for pid, doc in corpus.items():
        text = _doc_text(doc)
        terms = _tokenize(text)
        if not terms:
            continue

        doc_lengths[pid] = len(terms)

        tf_counts: Dict[str, int] = defaultdict(int)
        for t in terms:
            tf_counts[t] += 1

        for term, tf_td in tf_counts.items():
            index[term][pid] = tf_td

    if not doc_lengths:
        return []

    N = len(doc_lengths)
    avgdl = sum(doc_lengths.values()) / float(N)

    # 2. IDF per BM25 (versió log(N/df) com al report)
    idf: Dict[str, float] = {}
    for term, postings in index.items():
        df = len(postings)
        if df > 0:
            idf[term] = math.log(N / df)
        else:
            idf[term] = 0.0

    # 3. Processar la consulta
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    # Documents candidats: primer intentem intersecció (tots els termes),
    # i si queda buida, fem servir la unió (almenys un terme).
    candidate_docs = None  # tipus Optional[set[str]]

    for term in query_terms:
        postings = index.get(term)
        if not postings:
            continue
        docs_for_term = set(postings.keys())
        if candidate_docs is None:
            candidate_docs = docs_for_term
        else:
            candidate_docs &= docs_for_term

    if not candidate_docs:
        # Unió de tots els documents on surti algun terme
        candidate_docs = set()
        for term in query_terms:
            postings = index.get(term)
            if postings:
                candidate_docs.update(postings.keys())

    if not candidate_docs:
        return []

    # 4. Càlcul BM25
    k1 = 1.2
    b = 0.75
    doc_scores: Dict[str, float] = defaultdict(float)

    for term in query_terms:
        postings = index.get(term)
        if not postings:
            continue

        term_idf = idf.get(term, 0.0)
        if term_idf == 0.0:
            continue

        for pid, tf_td in postings.items():
            if pid not in candidate_docs:
                continue

            Ld = doc_lengths[pid]
            denom = k1 * ((1.0 - b) + b * (Ld / avgdl)) + tf_td
            score = term_idf * ((k1 + 1.0) * tf_td) / denom
            doc_scores[pid] += score

    if not doc_scores:
        return []

    # 5. Ordenar per score descendent
    ranked = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    #if top_k is not None:
    #    ranked = ranked[:top_k]

    # 6. Retornar Documents (sense afegir cap atribut extra)
    results: List[Document] = []

    for pid, _score in ranked:
        orig_doc = corpus[pid]

        # Fem una còpia del Document per poder canviar l'URL interna
        data = orig_doc.model_dump()
        data["url"] = f"doc_details?pid={orig_doc.pid}&search_id={search_id}"

        doc_copy = Document(**data)
        results.append(doc_copy)

    return results
