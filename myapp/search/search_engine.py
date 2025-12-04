import random
import numpy as np

from myapp.search.objects import Document
from myapp.search.algorithms import search_in_corpus, build_indexes


def dummy_search(corpus: dict, search_id, num_results=20):
    """
    Just a demo method, that returns random <num_results> documents from the corpus
    :param corpus: the documents corpus
    :param search_id: the search id
    :param num_results: number of documents to return
    :return: a list of random documents from the corpus
    """
    res = []
    doc_ids = list(corpus.keys())
    docs_to_return = np.random.choice(doc_ids, size=num_results, replace=False)
    for doc_id in docs_to_return:
        doc = corpus[doc_id]
        res.append(
            Document(
                pid=doc.pid,
                title=doc.title,
                description=doc.description,
                url="doc_details?pid={}&search_id={}&param2=2".format(
                    doc.pid, search_id
                ),
                ranking=random.random(),
            )
        )
    return res


class SearchEngine:
    """Class that implements the search engine logic"""

    # Initialize the index when the app is iniziated, so we do not have to create the indexes each time
    def __init__(self, corpus):
        self.corpus = corpus
        (
            self.index,
            self.field_index,
            self.idf,
            self.doc_length,
            self.avgdl,
        ) = build_indexes(corpus)

        print("SearchEngine: indexes built at startup.")
        print(f"  #docs = {len(self.doc_length)}")
        print(f"  avgdl = {self.avgdl}")


    def search(self, search_query, search_id, corpus):
        print("Search query:", search_query)
        # results = dummy_search(self.corpus, search_id)

        # Search with the precomputated indexes
        results = search_in_corpus(
            query=search_query,
            search_id=search_id,
            corpus=self.corpus,
            index=self.index,
            field_index=self.field_index,
            idf=self.idf,
            doc_length=self.doc_length,
            avgdl=self.avgdl,
        )
        return results
