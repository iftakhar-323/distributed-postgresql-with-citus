# Lab 46: Distributed Schema Design

In this lab, you will design a distributed database schema suitable for a multi-tenant application using Citus. You will learn the difference between distributed tables and reference tables, define SQLAlchemy models for `tenants`, `products`, and `orders`, and configure Citus to shard the `orders` table while keeping the `products` table available on all nodes as a reference table for global lookups.

<p align="center">
  <img src="https://raw.githubusercontent.com/poridhi-lab/lab-assets/main/citus-schema-design.png" alt="A high-level architectural diagram showing a Citus database cluster">
</p>

## Concept

| Term | Definition |
|---|---|
| Distributed Table | A table whose data is horizontally partitioned (sharded) across multiple worker nodes based on a distribution column (e.g., `tenant_id`). Ideal for large, frequently updated tables. |
| Reference Table | A table whose data is fully replicated to all worker nodes. Ideal for small, frequently joined lookup tables (e.g., product catalogs, country lists). |

In a multi-tenant e-commerce system, tables like `orders` grow rapidly and are always accessed in the context of a specific tenant. These should be distributed tables. Conversely, a `products` catalog might be shared across all tenants and is relatively small. Making `products` a reference table allows Citus to join `orders` and `products` locally on the worker nodes without network overhead.

## Objectives

- Understand the architectural differences between distributed and reference tables.
- Define SQLAlchemy models for `tenants`, `products`, and `orders`.
- Use `create_distributed_table` for the `orders` table.
- Use `create_reference_table` for the `products` table.

## Step 1: Update Database Models

Open **Terminal 1**, where we will edit our Flask app. We assume you already created `flask-citus-app` in the previous lab. Ensure your virtual environment is active.

```bash
cd ~/project/flask-citus-app
source venv/bin/activate
```

Now, overwrite the `database.py` file to include our new multi-tenant schema:

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
        except Exception as e:
            # Tables might already be distributed/referenced
            db.session.rollback()
            pass
EOF
```

**Expected Output:**
*(File created successfully. No terminal output.)*

## Step 2: Initialize Database and Start App

In **Terminal 1**, ensure any old processes on port 5000 are killed, and restart the Flask app. This will also execute the `setup_database` function to create the tables in Citus.

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
   WARNING: This is a development server. Do not use it in a production deployment.
 * Running on http://127.0.0.1:5000
```
*(Leave this running in the background).*

## Step 3: Verification

To verify that the tables were created and distributed correctly, we can connect directly to the Citus coordinator.

Open **Terminal 2** and run the following command to check the Citus metadata tables:

```bash
# Connect to the Citus coordinator container
docker exec -it citus-coordinator psql -U citus -d citus -c "SELECT logicalrelid, parttype FROM pg_dist_partition;"
```

**Expected Output:**
```text
 logicalrelid | parttype 
--------------+----------
 events       | h
 tenants      | h
 orders       | h
 products     | r
(4 rows)
```

| Output Type | Meaning |
|---|---|
| `h` | Hash distributed table. Data is sharded based on a hash of the distribution column. |
| `r` | Reference table. Data is fully replicated to all nodes. |

## Conclusion

You have successfully designed a distributed schema with Citus using Flask and SQLAlchemy. By intelligently choosing between distributed tables and reference tables, you ensure that your application scales horizontally while maintaining high performance for complex queries like joins.
