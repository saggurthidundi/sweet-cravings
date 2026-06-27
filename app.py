import os
import uuid
import razorpay
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient

# ==========================================
# 1. FLASK SETUP
# ==========================================
basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(basedir, 'templates')

app = Flask(__name__, template_folder=template_dir)
CORS(app) # Enables your local server to talk to the browser preview

# ==========================================
# 2. RAZORPAY TEST API SETUP
# ==========================================
# ⚠️ REPLACE THESE WITH YOUR ACTUAL RAZORPAY TEST KEYS
RAZORPAY_KEY_ID = "rzp_test_T4hduAOwiCqD2k"       
RAZORPAY_KEY_SECRET = "XF23mW11Sbu7qDrTy124EESe"
rzp_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ==========================================
# 3. MONGODB & CAKE CATALOG
# ==========================================
client = MongoClient("mongodb://localhost:27017/")
db = client["cake_db"]
cakes_collection = db["cakes"]
orders_collection = db["orders"]

# Temporarily drop the old products to apply the new 10rs product and new images!
cakes_collection.drop()

if cakes_collection.count_documents({}) == 0:
    print("Seeding database with premium cakes and addons...")
    cake_inventory = [
        {"id": "c1", "name": "Classic Black Forest", "price": 899.00, "category": "chocolate", "image": "https://images.unsplash.com/photo-1606890737304-57a1ca8a5b62?w=500", "rating": 4.8, "reviews": 320},
        {"id": "c2", "name": "Red Velvet Truffle", "price": 1099.00, "category": "premium", "image": "https://images.unsplash.com/photo-1616541823729-00fe0aacd32c?w=500", "rating": 4.9, "reviews": 450},
        {"id": "c3", "name": "Fresh Fruit Fiesta", "price": 949.00, "category": "fruit", "image": "https://images.unsplash.com/photo-1464349095431-e9a21285b5f3?w=500", "rating": 4.7, "reviews": 210},
        {"id": "c4", "name": "Dark Choco Lava Eggless", "price": 799.00, "category": "eggless", "image": "https://images.unsplash.com/photo-1624353365286-3f8d62daad51?w=500", "rating": 4.6, "reviews": 180},
        {"id": "c5", "name": "Vanilla Bean Cupcakes (Box of 6)", "price": 499.00, "category": "premium", "image": "https://images.unsplash.com/photo-1486427944299-d1955d23e34d?w=500", "rating": 4.8, "reviews": 510},
        {"id": "c6", "name": "Strawberry Cream Dream", "price": 849.00, "category": "fruit", "image": "https://images.unsplash.com/photo-1565958011703-44f9829ba187?w=500", "rating": 4.5, "reviews": 120},
        {"id": "c7", "name": "Gold Leaf Wedding Tier", "price": 4599.00, "category": "premium", "image": "https://images.unsplash.com/photo-1535141192574-5d4897c12636?w=500", "rating": 5.0, "reviews": 45},
        {"id": "c8", "name": "Hazelnut Chocolate Crunch", "price": 1199.00, "category": "chocolate", "image": "https://images.unsplash.com/photo-1542826438-bd32f43d626f?w=500", "rating": 4.9, "reviews": 35},
    ]
    cakes_collection.insert_many(cake_inventory)

# ==========================================
# 4. API ROUTES
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/products', methods=['GET'])
def get_products():
    products = list(cakes_collection.find({}, {'_id': 0}))
    return jsonify({"status": "success", "data": products}), 200

# Step 1 of Payment: Create Order
@app.route('/api/checkout', methods=['POST'])
def process_checkout():
    try:
        data = request.get_json()
        payment_method = data.get("payment_method")
        shipping_method = data.get("shipping_method", "Standard")
        shipping_cost = float(data.get("shipping_cost", 0))
        total_amount = float(data.get("total"))
        
        # Build our internal database record, including shipping info
        order_record = {
            "order_id": f"CAKE-{uuid.uuid4().hex[:6].upper()}",
            "customer_name": data.get("name"),
            "customer_address": data.get("address"),
            "shipping_method": shipping_method,
            "shipping_cost": shipping_cost,
            "items": data.get("cart"),
            "total_amount": total_amount,
            "payment_method": payment_method,
            "payment_status": "Pending",
            "created_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }

        if payment_method == "Razorpay":
            # Razorpay requires amount in Paise (multiply INR by 100)
            amount_in_paise = int(total_amount * 100)
            
            # Tell Razorpay server to create an order
            rzp_order = rzp_client.order.create({
                "amount": amount_in_paise,
                "currency": "INR",
                "payment_capture": "1" # Auto-capture payment
            })
            
            order_record["razorpay_order_id"] = rzp_order["id"]
            orders_collection.insert_one(order_record)
            order_record.pop('_id', None)
            
            return jsonify({
                "status": "success", 
                "gateway": "razorpay",
                "razorpay_order_id": rzp_order["id"],
                "key_id": RAZORPAY_KEY_ID,
                "amount_paise": amount_in_paise,
                "order_details": order_record
            }), 200

        else:
            # Handle Cash on Delivery
            order_record["payment_status"] = "Pending (COD)"
            orders_collection.insert_one(order_record)
            order_record.pop('_id', None)
            return jsonify({"status": "success", "gateway": "cod", "order_details": order_record}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Step 2 of Payment: Verify Signature
@app.route('/api/verify', methods=['POST'])
def verify_payment():
    data = request.get_json()
    try:
        # Check if the signature sent by the frontend is authentic
        rzp_client.utility.verify_payment_signature({
            'razorpay_order_id': data['razorpay_order_id'],
            'razorpay_payment_id': data['razorpay_payment_id'],
            'razorpay_signature': data['razorpay_signature']
        })
        
        # If no error is thrown, payment is verified! Update DB.
        orders_collection.update_one(
            {"razorpay_order_id": data['razorpay_order_id']},
            {"$set": {"payment_status": "Paid (Razorpay Verified)"}}
        )
        return jsonify({"status": "success"})
        
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"status": "error", "message": "Digital Signature Invalid. Payment Rejected."}), 400

# ==========================================
# 5. TIME-BASED TRACKING LOGIC
# ==========================================
@app.route('/api/track/<order_id>', methods=['GET'])
def track_order(order_id):
    try:
        order = orders_collection.find_one({"order_id": order_id}, {'_id': 0})
        if not order:
            return jsonify({"status": "error", "message": "Order not found"}), 404

        # Calculate exact time passed since order was placed
        created_at = datetime.strptime(order['created_at'], '%Y-%m-%d %H:%M:%S')
        now = datetime.utcnow()
        diff_minutes = (now - created_at).total_seconds() / 60.0

        # Timing Logic (1 minute intervals for testing)
        if diff_minutes < 1.0:
            status = "Order Received"
            progress_step = 1
        elif diff_minutes < 2.0:
            status = "Baking in Progress"
            progress_step = 2
        elif diff_minutes < 3.0:
            status = "Quality Check & Packaging"
            progress_step = 3
        elif diff_minutes < 4.0:
            status = "Out for Delivery"
            progress_step = 4
        else:
            status = "Delivered successfully"
            progress_step = 5

        return jsonify({
            "status": "success",
            "data": {
                "order_id": order["order_id"],
                "created_at": order["created_at"],
                "shipping_method": order.get("shipping_method", "Standard"),
                "customer_name": order["customer_name"],
                "total_amount": order["total_amount"],
                "current_status": status,
                "progress_step": progress_step,
                "minutes_elapsed": round(diff_minutes, 1)
            }
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)