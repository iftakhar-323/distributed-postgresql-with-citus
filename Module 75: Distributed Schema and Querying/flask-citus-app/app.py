import os
from flask import Flask, request, jsonify
from database import db, Tenant, Product, Order, setup_database

app = Flask(__name__)

COORDINATOR_IP = os.environ.get("COORDINATOR_IP", "127.0.0.1")
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://citus:citus_password@{COORDINATOR_IP}:5432/citus'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
setup_database(app)

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

@app.route('/orders', methods=['POST'])
def create_order():
    data = request.get_json()
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
