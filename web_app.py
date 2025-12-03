import os
from json import JSONEncoder

import httpagentparser  # for getting the user agent as json
from flask import Flask, render_template, session
from flask import request

from myapp.analytics.analytics_data import AnalyticsData, ClickedDoc
from myapp.search.load_corpus import load_corpus
from myapp.search.objects import Document, StatsDocument
from myapp.search.search_engine import SearchEngine
from myapp.generation.rag import RAGGenerator
from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env


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
# instantiate our search engine
search_engine = SearchEngine()
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
print("\nCorpus is loaded... \n First element:\n", list(corpus.values())[0])


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
    search_query = request.form['search-query']

    # Ensure session has unique ID
    if "session_id" not in session:
        import uuid
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    # Compute dwell time for last clicked doc
    analytics_data.compute_dwell(session_id)

    # 1 Save query
    query_event = analytics_data.save_query(session_id, search_query)

    # 2️ Assign mission
    mission_id = analytics_data.assign_mission(session_id, search_query)

    # Add mission to session info
    if "missions" not in analytics_data.fact_sessions[session_id]:
        analytics_data.fact_sessions[session_id]["missions"] = []
    analytics_data.fact_sessions[session_id]["missions"].append(mission_id)

    session['last_search_query'] = search_query
    session['last_mission_id'] = mission_id

    # 3️ Perform search
    results = search_engine.search(search_query, query_event.get("id"), corpus)

    # 4️ Save results ranking
    results_with_rank = [(doc.pid, idx+1) for idx, doc in enumerate(results)]
    analytics_data.save_results(session_id, search_query, results_with_rank)

    # 5️ Generate RAG response
    rag_response = rag_generator.generate_response(search_query, results)

    found_count = len(results)
    session['last_found_count'] = found_count

    return render_template(
        'results.html',
        results_list=results,
        page_title="Results",
        found_counter=found_count,
        rag_response=rag_response
    )


"""
@app.route('/doc_details', methods=['GET'])
def doc_details():
    """"""
    Show document details page
    ### Replace with your custom logic ###
    """"""

    # getting request parameters:
    # user = request.args.get('user')
    print("doc details session: ")
    print(session)

    res = session["some_var"]
    print("recovered var from session:", res)

    # get the query string parameters from request
    clicked_doc_id = request.args["pid"]
    print("click in id={}".format(clicked_doc_id))

    # store data in statistics table 1
    if clicked_doc_id in analytics_data.fact_clicks.keys():
        analytics_data.fact_clicks[clicked_doc_id] += 1
    else:
        analytics_data.fact_clicks[clicked_doc_id] = 1

    print("fact_clicks count for id={} is {}".format(clicked_doc_id, analytics_data.fact_clicks[clicked_doc_id]))
    print(analytics_data.fact_clicks)
    return render_template('doc_details.html')"""
    
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

    # 1️⃣ Register click + start dwell tracking
    analytics_data.save_doc_click(
        session_id,
        clicked_doc_id,
        corpus[clicked_doc_id].title,
        corpus[clicked_doc_id].description
    )

    # 2️⃣ Get the document
    doc = corpus[clicked_doc_id]

    return render_template(
        'doc_details.html',
        doc=doc,
        page_title="Document details"
    )


@app.route('/stats', methods=['GET'])
def stats():
    """
    Show full analytics: document clicks, dwell times, queries, HTTP, sessions
    """
    session_id = session["session_id"]
    analytics_data.compute_dwell(session_id)

    document_stats = analytics_data.get_document_stats()
    query_stats = analytics_data.get_query_stats()
    http_stats = {
        "requests": analytics_data.fact_http,
        "sessions": analytics_data.fact_sessions
    }

    return render_template(
        'stats.html',
        document_stats=document_stats,
        query_stats=query_stats,
        http_stats=http_stats,
        page_title="Analytics Overview"
    )



@app.route('/dashboard', methods=['GET'])
def dashboard():
    session_id = session["session_id"]
    analytics_data.compute_dwell(session_id)
    # Document stats
    ranked_docs = analytics_data.get_document_stats()

    # Query stats
    query_stats = analytics_data.get_query_stats()

    # HTTP stats
    http_requests = analytics_data.fact_http or []

    sessions = analytics_data.fact_sessions or {}

    # Extract user-agent safely
    user_agents = [str(r.get("user_agent", "Unknown")) for r in analytics_data.fact_http]

    return render_template(
        "dashboard.html",
        page_title="Analytics Dashboard",
        ranked_docs=ranked_docs,
        query_stats=query_stats,
        http_stats={
            "requests": analytics_data.fact_http,
            "sessions": sessions,
            "user_agents": user_agents,
        },
    )



# New route added for generating an examples of basic Altair plot (used for dashboard)
@app.route('/plot_number_of_views', methods=['GET'])
def plot_number_of_views():
    return analytics_data.plot_number_of_views()


if __name__ == "__main__":
    app.run(port=8088, host="0.0.0.0", threaded=False, debug=os.getenv("DEBUG"))
