import json
import random
import altair as alt
import pandas as pd
import requests
from myapp.search.algorithms import _tokenize


class AnalyticsData:
    """
    Complete analytics manager for:
    - HTTP request analytics
    - Session tracking
    - Queries analytics
    - Results analytics (ranking, shown docs)
    - Document clicks analytics
    - Dwell time tracking
    """

    def __init__(self):
        # Clicks {doc_id: count}
        self.fact_clicks = {}

        # Queries list of dicts
        self.fact_queries = []

        # Results list of dicts
        self.fact_results = []

        # Dwell time list of dicts
        self.fact_dwell = []

        # HTTP logs
        self.fact_http = []

        # Sessions
        self.fact_sessions = {}

        # Track last click to compute dwell
        self.last_click = {}

    # ----------------------------------------------------------------------
    # ----------------------------- HTTP -----------------------------------
    # ----------------------------------------------------------------------


    def get_location(self, ip: str):
        if ip.startswith("127.") or ip == "localhost":
            return "Localhost", "Localhost"
        try:
            res = requests.get(f"http://ip-api.com/json/{ip}", timeout=2)
            data = res.json()
            if data.get("status") == "success":
                return data.get("city", "Unknown"), data.get("country", "Unknown")
        except:
            pass
        return "Unknown", "Unknown"

    def save_http_request(self, request, session_id: str):
        ip = request.remote_addr
        city, country = self.get_location(ip)

        event = {
            "session_id": session_id,
            "path": request.path,
            "method": request.method,
            "ip": ip,
            "city": city,
            "country": country,
            "user_agent": str(request.user_agent),
            "timestamp": pd.Timestamp.now(),
        }
        self.fact_http.append(event)

        # Update session
        if session_id not in self.fact_sessions:
            self.fact_sessions[session_id] = {
                "start": event["timestamp"],
                "num_requests": 0,
                "num_queries": 0,
                "city": city,
                "country": country,
                "missions": [],  # initialize missions list
            }
        self.fact_sessions[session_id]["num_requests"] += 1


    
    # ----------------------------------------------------------------------
    # ----------------------------- Sessions -----------------------------------
    # ----------------------------------------------------------------------
    
    def update_physical_session(self, session_id: str):
        now = pd.Timestamp.now()
        session = self.fact_sessions.get(session_id)
        if session:
            last_time = session.get("last_activity", session["start"])
            if (now - last_time).total_seconds() > 1800:  # 30 min timeout
                # Create new session ID for this sit-down
                import uuid
                new_session_id = str(uuid.uuid4())
                self.fact_sessions[new_session_id] = {
                    "start": now,
                    "num_requests": 0,
                    "num_queries": 0,
                    "last_activity": now,
                }
                return new_session_id
            else:
                session["last_activity"] = now
        return session_id

    def assign_mission(self, session_id: str, query: str):
        """
        Assigna un mission_id fent servir similitud cosinus i els mateixos tokens
        preprocessats que el motor de cerca (_tokenize / preproces_text).
        """
        import math
        import pandas as pd
        import uuid
        from myapp.search.algorithms import _tokenize   # ⚠️ ajusta el path si cal

        session = self.fact_sessions.get(session_id)
        if not session:
            return None

        # -------------------------------
        # Helpers per TF i cosinus 
        # -------------------------------
        def build_tf(tokens):
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            return tf

        def cosine_sim(tf1, tf2):
            if not tf1 or not tf2:
                return 0.0
            common = set(tf1.keys()) & set(tf2.keys())
            num = sum(tf1[t] * tf2[t] for t in common)
            den1 = math.sqrt(sum(v * v for v in tf1.values()))
            den2 = math.sqrt(sum(v * v for v in tf2.values()))
            if den1 == 0 or den2 == 0:
                return 0.0
            return num / (den1 * den2)

        # -------------------------------
        # Preprocess de la query actual
        # -------------------------------
        now = pd.Timestamp.now()
        current_tokens = _tokenize(query)
        current_tf = build_tf(current_tokens)

        # -------------------------------
        # Paràmetres del model
        # -------------------------------
        TIME_WINDOW_SECONDS = 2 * 60 * 60      # 2 hores
        SIM_THRESHOLD = 0.35                   # llindar de similitud cosinus

        # -------------------------------
        # Busquem queries antigues amb missió
        # -------------------------------
        previous_queries = [
            q for q in self.fact_queries
            if q["session_id"] == session_id and "mission_id" in q
        ]

        best_sim = 0.0
        best_mission_id = None

        for q in previous_queries:
            # Finestra temporal
            if (now - q["timestamp"]).total_seconds() > TIME_WINDOW_SECONDS:
                continue

            prev_tokens = _tokenize(q["query"])
            prev_tf = build_tf(prev_tokens)
            sim = cosine_sim(current_tf, prev_tf)

            if sim > best_sim:
                best_sim = sim
                best_mission_id = q["mission_id"]

        # -------------------------------
        # Decisió: nova missió o mateixa?
        # -------------------------------
        if best_mission_id is None or best_sim < SIM_THRESHOLD:
            mission_id = str(uuid.uuid4())
        else:
            mission_id = best_mission_id

        # -------------------------------
        # Guardar la query
        # -------------------------------
        event = self.save_query(session_id, query)
        event["mission_id"] = mission_id

        # -------------------------------
        # Afegir missió a la sessió (sense duplicats)
        # -------------------------------
        if "missions" not in session:
            session["missions"] = []

        if mission_id not in session["missions"]:
            session["missions"].append(mission_id)

        return mission_id




    # ----------------------------------------------------------------------
    # ----------------------------- QUERIES --------------------------------
    # ----------------------------------------------------------------------

    def save_query(self, session_id: str, query: str):
        """
        Save query with metadata: terms, order, timestamp.
        """
        terms = query.split()
        event = {
            "session_id": session_id,
            "query": query,
            "num_terms": len(terms),
            "terms": terms,
            "timestamp": pd.Timestamp.now(),
        }
        self.fact_queries.append(event)

        if session_id not in self.fact_sessions:
            self.fact_sessions[session_id] = {"start": event["timestamp"],
                                              "num_requests": 0,
                                              "num_queries": 0}

        self.fact_sessions[session_id]["num_queries"] += 1
        return event

    # ----------------------------------------------------------------------
    # ----------------------------- RESULTS --------------------------------
    # ----------------------------------------------------------------------

    def save_results(self, session_id: str, query: str, results):
        """
        Save ranked results returned for a query.
        results: list of (doc_id, rank)
        """
        timestamp = pd.Timestamp.now()

        for doc_id, rank in results:
            self.fact_results.append({
                "session_id": session_id,
                "query": query,
                "doc_id": doc_id,
                "rank": rank,
                "timestamp": timestamp
            })

    # ----------------------------------------------------------------------
    # ---------------------- DOCUMENT CLICKS -------------------------------
    # ----------------------------------------------------------------------

    def save_doc_click(self, session_id: str, doc_id: str, title: str, description: str):
        """
        Save a click on a document and start dwell timer.
        """

        # Update click counter
        if doc_id not in self.fact_clicks:
            self.fact_clicks[doc_id] = 0
        self.fact_clicks[doc_id] += 1

        # Start dwell timing
        self.last_click[session_id] = (doc_id, pd.Timestamp.now())

        event = {
            "session_id": session_id,
            "doc_id": doc_id,
            "title": title,
            "description": description,
            "timestamp": pd.Timestamp.now()
        }

        return event

    # ----------------------------------------------------------------------
    # --------------------------- DWELL TIME -------------------------------
    # ----------------------------------------------------------------------

    def compute_dwell(self, session_id: str):
        """
        Called when returning to results page:
        Computes dwell time since last document click.
        """
        if session_id not in self.last_click:
            return None

        doc_id, click_time = self.last_click[session_id]
        dwell = (pd.Timestamp.now() - click_time).total_seconds()

        event = {
            "session_id": session_id,
            "doc_id": doc_id,
            "dwell_time": dwell,
            "timestamp": pd.Timestamp.now()
        }

        self.fact_dwell.append(event)
        del self.last_click[session_id]

        return event

    # ----------------------------------------------------------------------
    # --------------------------- VISUALIZATIONS ----------------------------
    # ----------------------------------------------------------------------

    def plot_number_of_views(self):
        """Return HTML of a plot showing # of views per document."""
        data = [
            {"Document ID": doc_id, "Number of Views": count}
            for doc_id, count in self.fact_clicks.items()
        ]

        if not data:
            return "<p>No click data yet.</p>"

        df = pd.DataFrame(data)

        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(x="Document ID", y="Number of Views")
            .properties(title="Number of Views per Document")
        )

        return chart.to_html()

    # ------------------- DOCUMENT STATS -------------------
    def get_document_stats(self):
        """
        Returns a list of documents with clicks, related queries, dwell times, and average dwell.
        """
        stats = []
        for doc_id, clicks in self.fact_clicks.items():
            related_queries = [
                log["query"] for log in self.fact_results if log["doc_id"] == doc_id
            ]
            dwell_times = [
                log["dwell_time"] for log in self.fact_dwell if log["doc_id"] == doc_id
            ]
            avg_dwell = sum(dwell_times)/len(dwell_times) if dwell_times else 0

            stats.append({
                "doc_id": doc_id,
                "clicks": clicks,
                "related_queries": related_queries,
                "dwell_times": dwell_times,
                "avg_dwell_time": avg_dwell
            })

        # Sort by clicks descending
        stats.sort(key=lambda x: x["clicks"], reverse=True)
        return stats

    # ------------------- QUERY STATS -------------------
    def get_query_stats(self):
        """
        Retorna estadístiques de les queries.

        - Agrupa per text de query.
        - Per a cada query: nombre de cops que s'ha fet ('count') i num_terms.
        """
        aggregated = {}  # text_query -> dict

        for q in self.fact_queries:
            text = q["query"]
            if text not in aggregated:
                aggregated[text] = {
                    "query": text,
                    "num_terms": q.get("num_terms", len(q.get("terms", []))),
                    "count": 1,
                }
            else:
                aggregated[text]["count"] += 1

        queries_list = list(aggregated.values())

        # Map query -> llista de doc_ids retornats (última versió)
        query_results_map = {}
        for q_text in aggregated.keys():
            query_results_map[q_text] = [
                r["doc_id"] for r in self.fact_results if r["query"] == q_text
            ]

        return {
            "total_queries": len(self.fact_queries),
            "queries": queries_list,
            "query_results": query_results_map,
        }



    


class ClickedDoc:
    def __init__(self, doc_id, description, counter):
        self.doc_id = doc_id
        self.description = description
        self.counter = counter

    def to_json(self):
        return self.__dict__

    def __str__(self):
        """
        Print the object content as a JSON string
        """
        return json.dumps(self)
