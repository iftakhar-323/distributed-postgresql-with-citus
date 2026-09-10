# Lab 47: Sharded Data API

In this lab, you will extend your Flask application to interact with the distributed database schema. You will build REST API endpoints to handle inserting new multi-tenant data and querying that sharded data efficiently across worker nodes.

<p align="center">
  <img src="https://raw.githubusercontent.com/poridhi-lab/lab-assets/main/citus-sharded-api.png" alt="A high-level system flow diagram showing an API interaction routing requests based on tenant_id">
</p>

## Concept

When interacting with a multi-tenant Citus database, the application layer should always include the distribution column (e.g., `tenant_id`) in queries and inserts. 
- For **Inserts**: Including the `tenant_id` allows the Citus coordinator to immediately route the new record directly to the target worker shard.
- For **Queries**: Including `tenant_id` in the `WHERE` clause allows Citus to push the query down to a single worker node (a single-shard router query), completely avoiding cross-node network traffic or expensive multi-shard scans.

---

## Objectives

- Verify or establish Citus cluster connectivity via Pulumi.
- Configure an isolated Python environment and connect securely via an SSH tunnel.
- Define the multi-tenant database models and distribution strategy.
- Build a `POST /orders` endpoint to insert new orders with tenant context.
- Build a `GET /orders/<tenant_id>` endpoint to retrieve orders for a specific tenant.
- Test the API using `curl` to observe seamless data routing.

---

## Prerequisites: Citus Cluster Connectivity

Before proceeding with this lab, verify that the Citus Coordinator (`controller-0`) is accessible:

```bash
ssh controller-0 "sudo docker ps"
```

> [!NOTE]
> - **If you already provisioned the cluster in Lab 44** in your current session, the command above will immediately succeed.
> - **If you are in a fresh Poridhi terminal/container**, configure AWS CLI and launch the Citus cluster using Pulumi:
>   ```bash
>   aws configure set aws_access_key_id "YOUR_ACCESS_KEY_HERE"
>   aws configure set aws_secret_access_key "YOUR_SECRET_KEY_HERE"
>   aws configure set default.region "ap-southeast-1"
>   aws configure set default.output "json"
>
>   cd ~/citus-infra || (git clone https://github.com/poridhioss/distributed-postgresql-with-citus.git /tmp/citus-repo && cp -r /tmp/citus-repo/citus-infra ~/citus-infra && cd ~/citus-infra)
>   python3 -m venv venv && source venv/bin/activate
>   pip install -r requirements.txt
>   pulumi up --yes
>   ```

---

## Step 1: Project Setup and Dependencies Installation

Open **Terminal 1** and set up the isolated project directory and virtual environment:

```bash
# 1. Create and navigate into the project directory
mkdir -p ~/project/flask-citus-app
cd ~/project/flask-citus-app

# 2. Define requirements.txt
cat << 'EOF' > requirements.txt
Flask==3.0.0
psycopg2-binary==2.9.9
Flask-SQLAlchemy==3.1.1
EOF

# 3. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

---

## Step 2: Establish SSH Tunnel to Citus Coordinator

The Citus Coordinator runs inside the AWS VPC on EC2 instance `controller-0` at port `5432`. Establish the background SSH tunnel forwarding port `5432` to localhost:

```bash
ssh -f -N -L 5432:localhost:5432 controller-0
```

---

## Step 3: Define Database Schema and Distribution

In **Terminal 1**, create `database.py` to define the models (`Tenant`, `Product`, `Order`) and distribute them across Citus worker nodes:

```bash
cat << 'EOF' > database.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

db = SQLAlchemy()

class Tenant(db.Model):
    __tablename__ = 'tenants'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)

class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

def setup_database(app):
    with app.app_context():
        db.create_all()
        
        # Distribute tenants and orders
        distribute_tenants = text("SELECT create_distributed_table('tenants', 'id');")
        distribute_orders = text("SELECT create_distributed_table('orders', 'tenant_id');")
        
        # Make products a reference table
        reference_products = text("SELECT create_reference_table('products');")
        
        try:
            db.session.execute(distribute_tenants)
            db.session.execute(distribute_orders)
            db.session.execute(reference_products)
            db.session.commit()
        except Exception:
            db.session.rollback()
            pass
EOF
```

Verify that `database.py` wrote cleanly:

```bash
tail -n 5 database.py
```

---

## Step 4: Implement Sharded REST API Endpoints

In **Terminal 1**, write `app.py` containing the API endpoints for managing tenants, reference products, and sharded orders:

```bash
cat << 'EOF' > app.py
import os
from flask import Flask, request, jsonify
from database import db, Tenant, Product, Order, setup_database

app = Flask(__name__)

COORDINATOR_IP = os.environ.get("COORDINATOR_IP", "127.0.0.1")
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://citus:citus_password@{COORDINATOR_IP}:5432/citus'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
setup_database(app)

# --- Helper Routes for Setup ---

@app.route('/tenants', methods=['POST'])
def create_tenant():
    data = request.get_json()
    new_tenant = Tenant(name=data['name'])
    db.session.add(new_tenant)
    db.session.commit()
    return jsonify({"message": "Tenant created", "id": new_tenant.id}), 201

@app.route('/products', methods=['POST'])
def create_product():
    data = request.get_json()
    new_product = Product(name=data['name'], price=data['price'])
    db.session.add(new_product)
    db.session.commit()
    return jsonify({"message": "Product created", "id": new_product.id}), 201

# --- Core Order Routes ---

@app.route('/orders', methods=['POST'])
def create_order():
    data = request.get_json()
    
    # tenant_id is explicitly provided to route to the correct shard
    new_order = Order(
        tenant_id=data['tenant_id'],
        product_id=data['product_id'],
        quantity=data['quantity']
    )
    
    db.session.add(new_order)
    db.session.commit()
    return jsonify({
        "message": "Order created", 
        "order_id": new_order.id, 
        "tenant_id": new_order.tenant_id
    }), 201

@app.route('/orders/<int:tenant_id>', methods=['GET'])
def get_orders(tenant_id):
    # Querying by tenant_id ensures a single-shard lookup
    orders = Order.query.filter_by(tenant_id=tenant_id).all()
    
    result = [{
        "id": o.id, 
        "tenant_id": o.tenant_id, 
        "product_id": o.product_id, 
        "quantity": o.quantity
    } for o in orders]
    
    return jsonify(result), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
EOF
```

Verify that `app.py` was created completely:

```bash
tail -n 5 app.py
```

---

## Step 5: Start the Flask API

Release port 5000 if occupied, and start the Flask API in **Terminal 1**:

```bash
sudo fuser -k 5000/tcp 2>/dev/null || true
export COORDINATOR_IP="127.0.0.1"
python3 app.py
```

**Expected Output:**
```text
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://10.61.9.121:5000
Press CTRL+C to quit
```

*(Leave this running in Terminal 1).*

---

## Step 6: Verification and Testing

Open **Terminal 2** to test the API endpoints using `curl`.

### Scenario 1: Create a Tenant

```bash
curl -s -X POST http://localhost:5000/tenants \
     -H "Content-Type: application/json" \
     -d '{"name": "Acme Corp"}'
echo ""
```

**Expected Output:**
```json
{"id":1,"message":"Tenant created"}
```

---

### Scenario 2: Create a Reference Product

```bash
curl -s -X POST http://localhost:5000/products \
     -H "Content-Type: application/json" \
     -d '{"name": "Widget", "price": 19.99}'
echo ""
```

**Expected Output:**
```json
{"id":1,"message":"Product created"}
```

---

### Scenario 3: Insert a Sharded Order

```bash
curl -s -X POST http://localhost:5000/orders \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": 1, "product_id": 1, "quantity": 5}'
echo ""
```

**Expected Output:**
```json
{"message":"Order created","order_id":1,"tenant_id":1}
```

---

### Scenario 4: Query Sharded Orders by Tenant

```bash
curl -s -X GET http://localhost:5000/orders/1
echo ""
```

**Expected Output:**
```json
[{"id":1,"product_id":1,"quantity":5,"tenant_id":1}]
```

---

### Scenario 5: Direct Verification on Citus Coordinator

Connect to the Citus Coordinator to verify that the row is stored in the distributed `orders` table:

```bash
ssh controller-0 "sudo docker exec -i citus_coordinator psql -U citus -d citus -c 'SELECT * FROM orders;'"
```

**Expected Output:**
```text
 id | tenant_id | product_id | quantity 
----+-----------+------------+----------
  1 |         1 |          1 |        5
(1 row)
```

---

## Conclusion

You have successfully built an API layer that inserts and queries sharded data in a multi-tenant PostgreSQL environment. Because the application correctly uses the distribution column (`tenant_id`), Citus can seamlessly and efficiently route database operations directly to the shards that hold the data.

You are now ready to proceed to **Lab 48: Query Plan Analysis and Benchmarking**!
