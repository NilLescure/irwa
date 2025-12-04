import os
from json import JSONEncoder

import httpagentparser  # for getting the user agent as json
from flask import Flask, render_template, session
from flask import request, redirect, url_for

from myapp.analytics.analytics_data import AnalyticsData, ClickedDoc
from myapp.search.load_corpus import load_corpus
from myapp.search.objects import Document, StatsDocument
from myapp.search.search_engine import SearchEngine
from myapp.generation.rag import RAGGenerator
from dotenv import load_dotenv
from collections import Counter

load_dotenv()  # take environment variables from .env

import math
PER_PAGE = 20

# *** for using method to_json in objects ***
def _default(self, obj):
    return getattr(obj.__class__, "to_json", _default.default)(obj)
_default.default = JSONEncoder().default
JSONEncoder.default = _default
# end lines ***for using method to_json in objects ***


# instantiate the Flask application
app = Flask(__name__)

# random 'secret_key' is used for persisting data in secure cookie
app.secret_key = os.getenv("SECRET_KEY")
# open browser dev tool to see the cookies
app.session_cookie_name = os.getenv("SESSION_COOKIE_NAME")
# instantiate our in memory persistence
analytics_data = AnalyticsData()
# instantiate RAG generator
rag_generator = RAGGenerator()

# load documents corpus into memory.
full_path = os.path.realpath(__file__)
path, filename = os.path.split(full_path)
file_path = path + "/" + os.getenv("DATA_FILE_PATH")
corpus = load_corpus(file_path)
# Log first element of corpus to verify it loaded correctly:
print("\nCorpus is loaded... \n First element:")#, list(corpus.values())[0])

# Instantiate our search engine (creating the indexes with the corpus)
search_engine = SearchEngine(corpus)

# Home URL "/"
@app.route('/')
def index():
    print("starting home url /...")

    # flask server creates a session by persisting a cookie in the user's browser.
    # the 'session' object keeps data between multiple requests. Example:
    session['some_var'] = "Some value that is kept in session"

    user_agent = request.headers.get('User-Agent')
    print("Raw user browser:", user_agent)

    user_ip = request.remote_addr
    agent = httpagentparser.detect(user_agent)

    print("Remote IP: {} - JSON user browser {}".format(user_ip, agent))
    print(session)
    return render_template('index.html', page_title="Welcome")

@app.before_request
def log_request():
    # Ensure session has unique ID
    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())

    # Update physical session
    session["session_id"] = analytics_data.update_physical_session(session["session_id"])

    # Save HTTP request
    analytics_data.save_http_request(request, session["session_id"])

    
    
@app.route('/search', methods=['POST'])
def search_form_post():
    # Query de la cerca
    search_query = request.form['search-query'].strip()

    page = int(request.form.get('page', 1))

    # Ensure session has unique ID
    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    # Compute dwell time for last clicked doc
    analytics_data.compute_dwell(session_id)

    mission_id = analytics_data.assign_mission(session_id, search_query)
    query_id = len(analytics_data.fact_queries)

    session['last_search_query'] = search_query
    session['last_mission_id'] = mission_id
    session['last_search_page'] = page

    # 3️ Perform search (llista completa de resultats)
    results = search_engine.search(search_query, query_id, corpus)

    # 4️ Save results ranking
    results_with_rank = [(doc.pid, idx + 1) for idx, doc in enumerate(results)]
    analytics_data.save_results(session_id, search_query, results_with_rank)

    # 5️ Generate RAG response
    rag_response = rag_generator.generate_response(search_query, results)

    # Comptador total
    found_count = len(results)
    session['last_found_count'] = found_count

    # Pagination
    total_pages = max(1, math.ceil(found_count / PER_PAGE)) if found_count else 1

    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_results = results[start_idx:end_idx]

    pages = []

    if total_pages <= 7:
        pages = list(range(1, total_pages + 1))
    else:
        pages.append(1)
        start_window = max(2, page - 2)
        end_window = min(total_pages - 1, page + 2)
        pages.extend(range(start_window, end_window + 1))
        pages.append(total_pages)
        seen = set()
        visible_pages = []
        for p in pages:
            if p not in seen:
                visible_pages.append(p)
                seen.add(p)
        pages = visible_pages

    return render_template(
        'results.html',
        results_list=page_results,
        page_title="Results",
        found_counter=found_count,
        rag_response=rag_response,
        search_query=search_query,
        page=page,
        total_pages=total_pages,
        pages=pages,
    )

@app.route('/last_search', methods=['GET'])
def last_search():
    search_query = session.get('last_search_query', '')
    if not search_query:
        return redirect(url_for('index'))

    page = int(session.get('last_search_page', 1))

    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]
    analytics_data.compute_dwell(session_id)
    mission_id = analytics_data.assign_mission(session_id, search_query)
    query_id = len(analytics_data.fact_queries)

    session['last_search_query'] = search_query
    session['last_mission_id'] = mission_id
    session['last_search_page'] = page

    results = search_engine.search(search_query, query_id, corpus)
    results_with_rank = [(doc.pid, idx + 1) for idx, doc in enumerate(results)]
    analytics_data.save_results(session_id, search_query, results_with_rank)
    rag_response = rag_generator.generate_response(search_query, results)
    found_count = len(results)
    session['last_found_count'] = found_count

    total_pages = max(1, math.ceil(found_count / PER_PAGE)) if found_count else 1
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    page_results = results[start_idx:end_idx]

    pages = []
    if total_pages <= 7:
        pages = list(range(1, total_pages + 1))
    else:
        pages.append(1)
        start_window = max(2, page - 2)
        end_window = min(total_pages - 1, page + 2)
        pages.extend(range(start_window, end_window + 1))
        pages.append(total_pages)

        seen = set()
        visible_pages = []
        for p in pages:
            if p not in seen:
                visible_pages.append(p)
                seen.add(p)
        pages = visible_pages

    return render_template(
        'results.html',
        results_list=page_results,
        page_title="Results",
        found_counter=found_count,
        rag_response=rag_response,
        search_query=search_query,
        page=page,
        total_pages=total_pages,
        pages=pages,
    )

    
@app.route('/doc_details', methods=['GET'])
def doc_details():
    """
    Show document details page with analytics tracking
    """

    # Ensure session has unique ID
    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]
    analytics_data.compute_dwell(session_id)

    clicked_doc_id = request.args["pid"]
    query_text = session.get("last_search_query", None)

    # Register click + start dwell tracking
    analytics_data.save_doc_click(
        session_id,
        clicked_doc_id,
        corpus[clicked_doc_id].title,
        corpus[clicked_doc_id].description
    )

    # Get the document
    doc = corpus[clicked_doc_id]

    return render_template(
        'doc_details.html',
        doc=doc,
        page_title="Document details",
        last_search_url=url_for('last_search'),
    )



@app.route('/stats', methods=['GET'])
def stats():
    """
    Show full analytics: document clicks, dwell times, queries, HTTP, sessions, missions
    """
    session_id = session.get("session_id")
    if session_id:
        analytics_data.compute_dwell(session_id)

    # Data
    document_stats = analytics_data.get_document_stats()
    query_stats = analytics_data.get_query_stats()
    raw_queries = analytics_data.fact_queries
    http_requests = analytics_data.fact_http
    sessions = analytics_data.fact_sessions
    dwell_events = analytics_data.fact_dwell

    # Summary global
    total_clicks = sum(d["clicks"] for d in document_stats)
    total_docs_clicked = len(document_stats)

    total_dwell_events = len(dwell_events)
    total_dwell_time = sum(e["dwell_time"] for e in dwell_events) if total_dwell_events else 0
    avg_dwell_global = total_dwell_time / total_dwell_events if total_dwell_events else 0

    total_queries = len(raw_queries)
    unique_queries = len({q["query"] for q in raw_queries}) if raw_queries else 0

    total_sessions = len(sessions)
    total_requests = len(http_requests)

    method_counts = Counter(r["method"] for r in http_requests) if http_requests else {}

    summary = {
        "total_clicks": total_clicks,
        "total_docs_clicked": total_docs_clicked,
        "total_dwell_events": total_dwell_events,
        "total_dwell_time": total_dwell_time,
        "avg_dwell_time": avg_dwell_global,
        "total_queries": total_queries,
        "unique_queries": unique_queries,
        "total_sessions": total_sessions,
        "total_requests": total_requests,
    }

    # Missions
    missions = {}
    for q in raw_queries:
        mission_id = q.get("mission_id")
        if not mission_id:
            continue

        m = missions.setdefault(
            mission_id,
            {
                "mission_id": mission_id,
                "session_id": q["session_id"],
                "queries": [],
                "start": q["timestamp"],
                "end": q["timestamp"],
            },
        )
        m["queries"].append(q["query"])
        if q["timestamp"] < m["start"]:
            m["start"] = q["timestamp"]
        if q["timestamp"] > m["end"]:
            m["end"] = q["timestamp"]

    for m in missions.values():
        m["num_queries"] = len(m["queries"])
        m["unique_queries"] = len(set(m["queries"]))
        if m["start"] and m["end"]:
            m["duration_seconds"] = (m["end"] - m["start"]).total_seconds()
        else:
            m["duration_seconds"] = 0

    mission_list = sorted(missions.values(), key=lambda x: x["start"]) if missions else []

    mission_summary = {
        "total_missions": len(mission_list),
        "avg_queries_per_mission": (
            sum(m["num_queries"] for m in mission_list) / len(mission_list)
        ) if mission_list else 0,
    }

    http_stats = {
        "requests": http_requests,
        "sessions": sessions,
        "method_counts": method_counts,
    }

    return render_template(
        'stats.html',
        page_title="Analytics Overview",
        document_stats=document_stats,
        query_stats=query_stats,
        raw_queries=raw_queries,
        http_stats=http_stats,
        summary=summary,
        mission_stats={
            "summary": mission_summary,
            "missions": mission_list,
        },
    )



@app.route('/dashboard', methods=['GET'])
def dashboard():
    session_id = session["session_id"]
    analytics_data.compute_dwell(session_id)

    # Document stats
    ranked_docs = analytics_data.get_document_stats()

    enhanced_docs = []
    for d in ranked_docs:
        doc_id = d["doc_id"]
        doc_title = corpus[doc_id].title if doc_id in corpus else f"Document {doc_id}"
        d_copy = d.copy()
        d_copy["title"] = doc_title
        enhanced_docs.append(d_copy)

    # Query stats
    query_stats = analytics_data.get_query_stats()

    # HTTP stats
    http_requests = analytics_data.fact_http or []
    sessions = analytics_data.fact_sessions or {}

    # Actual session
    current_session = sessions.get(session_id, {
        "city": "Unknown",
        "country": "Unknown",
        "missions": []
    })

    # User-agents
    user_agents = [str(r.get("user_agent", "Unknown")) for r in analytics_data.fact_http]

    return render_template(
        "dashboard.html",
        page_title="Analytics Dashboard",
        ranked_docs=enhanced_docs,
        query_stats=query_stats,
        http_stats={
            "requests": analytics_data.fact_http,
            "sessions": sessions,
            "user_agents": user_agents,
        },
        current_session=current_session,
    )



# New route added for generating an examples of basic Altair plot (used for dashboard)
@app.route('/plot_number_of_views', methods=['GET'])
def plot_number_of_views():
    return analytics_data.plot_number_of_views()


if __name__ == "__main__":
    app.run(port=8088, host="0.0.0.0", threaded=False, debug=os.getenv("DEBUG"))
