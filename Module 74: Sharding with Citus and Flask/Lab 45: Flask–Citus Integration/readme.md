# Lab 45: Flask–Citus Integration

In this lab, you will build a Python REST API using Flask and SQLAlchemy that connects to a distributed Citus cluster. You will create endpoints to handle multi-tenant data, inserting and querying records across sharded tables. This demonstrates how a standard Flask application interacts seamlessly with Citus just like regular PostgreSQL.

<p align="center">
  <img src="https://raw.githubusercontent.com/poridhi-lab/lab-assets/main/citus-flask-arch.png" alt="A high-level architecture diagram showing a Flask API receiving HTTP requests and connecting to the Citus Coordinator node">
</p>

## Concept

| Term | Definition |
|---|---|
| SQLAlchemy | A SQL toolkit and Object-Relational Mapping (ORM) library for Python. |
| Distribution Column | The column used by Citus to shard data across worker nodes (e.g., `tenant_id`). |
| Multi-tenant | An architecture where a single instance of a software application serves multiple customers (tenants), isolated by a tenant ID. |

Citus is fully compatible with standard PostgreSQL drivers like `psycopg2`. This means your Flask application does not need any specialized Citus libraries to work. You simply define your models, mark the table as distributed by executing a specific Citus function (`create_distributed_table`), and ensure all queries include the distribution column to efficiently route them to the correct shards.

<p align="center">
  <img src="https://raw.githubusercontent.com/poridhi-lab/lab-assets/main/citus-flask-flow.png" alt="A lifecycle flow diagram showing Client POSTs data to Flask, ORM translates to SQL, Coordinator hashes tenant_id">
</p>

## Objectives

- Configure a Python virtual environment with Flask and SQLAlchemy.
- Implement a multi-tenant database model.
- Build REST endpoints to insert and retrieve sharded data.
- Verify distributed query execution and data insertion.

## Step 1: Create the Project Dependencies

Open **Terminal 1** and run the following commands to create the directory and the `requirements.txt` file:

```bash
mkdir -p ~/project/flask-citus-app
cd ~/project/flask-citus-app

cat <<EOF > requirements.txt
Flask==3.0.0
psycopg2-binary==2.9.9
Flask-SQLAlchemy==3.1.1
EOF
```

**Expected Output:**
*(No output is expected, but you can verify by running `cat requirements.txt`)*

## Step 2: Install Dependencies

In the same terminal (**Terminal 1**), create and activate an isolated Python virtual environment, then install the dependencies.

```bash
cd ~/project/flask-citus-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Expected Output:**
```text
Collecting Flask==3.0.0
...
Successfully installed Flask-3.0.0 Flask-SQLAlchemy-3.1.1 ...
```

## Step 3: Implement Database Connection and Schema

In **Terminal 1**, create `database.py`:

```bash
cat << 'EOF' > database.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

db = SQLAlchemy()

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(100), nullable=False)
    
def setup_database(app):
    with app.app_context():
        db.create_all()
        distribute_query = text("SELECT create_distributed_table('events', 'tenant_id');")
        try:
            db.session.execute(distribute_query)
            db.session.commit()
        except Exception:
            db.session.rollback()
            pass
EOF
```

**Expected Output:**
*(File created successfully. No terminal output.)*

## Step 4: Implement the Flask Application

In **Terminal 1**, create `app.py`:

```bash
cat << 'EOF' > app.py
import os
from flask import Flask, request, jsonify
from database import db, Event, setup_database

app = Flask(__name__)

COORDINATOR_IP = os.environ.get("COORDINATOR_IP", "127.0.0.1")
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://citus:citus_password@{COORDINATOR_IP}:5432/citus'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
setup_database(app)

@app.route('/events', methods=['POST'])
def create_event():
    data = request.get_json()
    new_event = Event(
        tenant_id=data['tenant_id'],
        event_name=data['event_name']
    )
    db.session.add(new_event)
    db.session.commit()
    return jsonify({"message": "Event created", "tenant_id": new_event.tenant_id}), 201

@app.route('/events/<int:tenant_id>', methods=['GET'])
def get_events(tenant_id):
    events = Event.query.filter_by(tenant_id=tenant_id).all()
    result = [{"id": e.id, "tenant_id": e.tenant_id, "event_name": e.event_name} for e in events]
    return jsonify(result), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
EOF
```

**Expected Output:**
*(File created successfully. No terminal output.)*

## Step 5: Start the Flask API

Before starting the server, ensure no other service is using port 5000. Stop any existing processes if necessary:

```bash
# Clean up any existing process on port 5000
sudo fuser -k 5000/tcp 2>/dev/null || true
```

In **Terminal 1**, ensure your virtual environment is still active, then start the Flask app:

```bash
cd ~/project/flask-citus-app
source venv/bin/activate
export COORDINATOR_IP="10.0.1.10"
python3 app.py
```

**Expected Output:**
```text
 * Serving Flask app 'app'
 * Debug mode: off
 * Running on all addresses (0.0.0.0)
   WARNING: This is a development server. Do not use it in a production deployment.
 * Running on http://127.0.0.1:5000
```
*(Leave this terminal running. Do not close it or press Ctrl+C until the lab is complete.)*

## Step 6: Verification

Open a new terminal (**Terminal 2**). You do not need the virtual environment active just to run `curl` commands.

**Scenario 1: Create an event (Success)**

```bash
curl -X POST http://localhost:5000/events \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": 101, "event_name": "User Signup"}'
```

**Expected Output:**
```json
{
  "message": "Event created",
  "tenant_id": 101
}
```

**Scenario 2: Retrieve events for a specific tenant (Success)**

```bash
curl -X GET http://localhost:5000/events/101
```

**Expected Output:**
```json
[
  {
    "event_name": "User Signup",
    "id": 1,
    "tenant_id": 101
  }
]
```

## Conclusion

You have successfully built a Flask API integrated with a Citus cluster. By utilizing SQLAlchemy and defining a distribution column, the application efficiently routes data and queries to the appropriate distributed shards seamlessly.
