import os
import sqlite3
from statistics import mean

from flask import Flask, abort, g, redirect, render_template, request, url_for

app = Flask(__name__)

# On Railway, attach a volume and its mount path is exposed as
# RAILWAY_VOLUME_MOUNT_PATH; otherwise fall back to a local file.
DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(DATA_DIR, "memory.db"))

WORD_LISTS = {
    "list1": ["Reason", "Treatment", "Study", "Dumpster", "Index", "Phantom", "Canyon", "Engine",
              "Hardware", "Album", "Gadget", "Freezer", "Jacket", "Random", "Stapler", "Bleacher"],
    "list2": ["Dandruff", "Razor", "Bounty", "Neutron", "Logic", "Theory", "Bottom", "Kayak",
              "Elbow", "Sweater", "Resort", "Handle", "Yellow", "Concert", "Address", "Morning"],
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS srt (value INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS word_counts ("
                   "list_name TEXT NOT NULL, word TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, "
                   "PRIMARY KEY (list_name, word))")
        db.execute("CREATE TABLE IF NOT EXISTS submissions ("
                   "list_name TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)")


init_db()


def winsorized_mean(values, proportion=0.2):
    """Replace the lowest/highest `proportion` of values with the nearest remaining value."""
    s = sorted(values)
    k = int(len(s) * proportion)
    if k:
        s = [s[k]] * k + s[k:-k] + [s[-k - 1]] * k
    return mean(s)


@app.route("/")
def index():
    return render_template("index.html")


# ---------- Serial recall task ----------

@app.route("/srt", methods=["GET", "POST"])
def srt():
    error = None
    if request.method == "POST":
        try:
            value = int(request.form.get("value", ""))
        except ValueError:
            value = None
        if value is None or not 0 <= value <= 99:
            error = "Please enter a whole number from 0 to 99."
        else:
            db = get_db()
            db.execute("INSERT INTO srt (value) VALUES (?)", (value,))
            db.commit()
            return redirect(url_for("srt", done=1))
    return render_template("srt.html", done=request.args.get("done"), error=error)


@app.route("/srt-reset", methods=["GET", "POST"])
def srt_reset():
    if request.method == "POST":
        db = get_db()
        db.execute("DELETE FROM srt")
        db.commit()
        return render_template("reset.html", what="SRT results", cleared=True)
    return render_template("reset.html", what="SRT results", cleared=False)


@app.route("/srt-graph")
def srt_graph():
    values = [row[0] for row in get_db().execute("SELECT value FROM srt")]
    if values:
        title = f"Average: {mean(values):.2f} ({winsorized_mean(values):.2f})"
        labels = list(range(min(values), max(values) + 1))
        counts = [values.count(v) for v in labels]
    else:
        title, labels, counts = "Average: — (no responses yet)", [], []
    return render_template("graph.html", kind="bar", title=title, labels=labels, counts=counts,
                           x_label="Number remembered correctly", y_label="Number of students",
                           n=len(values))


# ---------- Word lists ----------

def check_list(name):
    if name not in WORD_LISTS:
        abort(404)
    return WORD_LISTS[name]


@app.route("/<name>", methods=["GET", "POST"])
def word_list(name):
    words = check_list(name)
    if request.method == "POST":
        checked = [w for w in words if request.form.get(w)]
        db = get_db()
        for w in checked:
            db.execute("INSERT INTO word_counts (list_name, word, count) VALUES (?, ?, 1) "
                       "ON CONFLICT(list_name, word) DO UPDATE SET count = count + 1", (name, w))
        db.execute("INSERT INTO submissions (list_name, count) VALUES (?, 1) "
                   "ON CONFLICT(list_name) DO UPDATE SET count = count + 1", (name,))
        db.commit()
        return redirect(url_for("word_list", name=name, done=1))
    return render_template("word_list.html", name=name, words=words, done=request.args.get("done"))


@app.route("/<name>-reset", methods=["GET", "POST"])
def word_list_reset(name):
    check_list(name)
    label = f"{name} results"
    if request.method == "POST":
        db = get_db()
        db.execute("DELETE FROM word_counts WHERE list_name = ?", (name,))
        db.execute("DELETE FROM submissions WHERE list_name = ?", (name,))
        db.commit()
        return render_template("reset.html", what=label, cleared=True)
    return render_template("reset.html", what=label, cleared=False)


@app.route("/<name>-graph")
def word_list_graph(name):
    words = check_list(name)
    db = get_db()
    stored = dict(db.execute("SELECT word, count FROM word_counts WHERE list_name = ?", (name,)))
    row = db.execute("SELECT count FROM submissions WHERE list_name = ?", (name,)).fetchone()
    n = row[0] if row else 0
    counts = [stored.get(w, 0) for w in words]
    title = f"{name.capitalize()}: words recalled by position"
    return render_template("graph.html", kind="line", title=title, labels=words, counts=counts,
                           x_label="Word (presentation order)", y_label="Number of students",
                           n=n)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
