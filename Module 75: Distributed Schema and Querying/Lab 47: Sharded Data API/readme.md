# Lab 47: Sharded Data API

In this lab, you will extend your Flask application to interact with the distributed database schema created in the previous lab. You will build REST API endpoints to handle inserting new multi-tenant data and querying that sharded data efficiently.

<p align="center">
  <img src="https://raw.githubusercontent.com/poridhi-lab/lab-assets/main/citus-sharded-api.png" alt="A high-level system flow diagram showing an API interaction routing requests based on tenant_id">
</p>

## Concept

When interacting with a multi-tenant Citus database, the application layer should always include the distribution column (e.g., `tenant_id`) in queries and inserts. 
- For **Inserts**: Including the `tenant_id` allows the Citus coordinator to immediately route the new record to the correct worker shard.
- For **Queries**: Including `tenant_id` in the `WHERE` clause allows Citus to push the query down to a single worker node, completely avoiding cross-node network traffic or full table scans.

## Objectives

- Build a `POST /orders` endpoint to insert new orders with tenant context.
- Build a `GET /orders/<tenant_id>` endpoint to retrieve orders for a specific tenant.
- Test the API using `curl` to observe seamless data routing.

## Step 1: Implement the API Endpoints

Open **Terminal 1** (ensure your virtual environment is active). We will update the `app.py` file to include routing for the `orders`, `tenants`, and `products` models.

```bash
cd ~/project/flask-citus-app
source venv/bin/activate

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

**Expected Output:**
*(File updated successfully. No terminal output.)*

## Step 2: Start the Flask API

Restart the Flask API so the new routes take effect. In **Terminal 1**:

```bash
sudo fuser -k 5000/tcp 2>/dev/null || true
export COORDINATOR_IP="10.0.1.10"
python3 app.py
```

**Expected Output:**
```text
 * Serving Flask app 'app'
 * Debug mode: off
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
```
*(Leave this running in the background).*

## Step 3: Verification

Open **Terminal 2** to run the following tests.

**Scenario 1: Setup reference data (Products) and a Tenant**

```bash
# Create a tenant
curl -s -X POST http://localhost:5000/tenants \
     -H "Content-Type: application/json" \
     -d '{"name": "Acme Corp"}'
echo ""
```

**Expected Output:**
```json
{"id":1,"message":"Tenant created"}
```

```bash
# Create a product (Reference Data)
curl -s -X POST http://localhost:5000/products \
     -H "Content-Type: application/json" \
     -d '{"name": "Widget", "price": 19.99}'
echo ""
```

**Expected Output:**
```json
{"id":1,"message":"Product created"}
```

**Scenario 2: Insert a Sharded Order (Success)**

```bash
# Insert an order for Acme Corp (tenant_id 1) and Widget (product_id 1)
curl -s -X POST http://localhost:5000/orders \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": 1, "product_id": 1, "quantity": 5}'
echo ""
```

**Expected Output:**
```json
{"message":"Order created","order_id":1,"tenant_id":1}
```

**Scenario 3: Query Sharded Orders by Tenant (Success)**

```bash
curl -s -X GET http://localhost:5000/orders/1
echo ""
```

**Expected Output:**
```json
[{"id":1,"product_id":1,"quantity":5,"tenant_id":1}]
```

## Conclusion

You have successfully built an API layer that inserts and queries sharded data in a multi-tenant PostgreSQL environment. Because the application correctly uses the distribution column (`tenant_id`), Citus can seamlessly and efficiently route database operations directly to the shards that hold the data.
