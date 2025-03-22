from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import razorpay
from database import students_collection, vendors_collection, transactions_collection
from models import PaymentRequest, WalletRechargeRequest, VerifyPayment, StudentPaymentRequest, StudentQRData
from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
import qrcode
from io import BytesIO
import base64
import json
from bson import ObjectId
import datetime
import os
import hmac
import hashlib
from utils.sms_utils import send_payment_notification, verify_otp, format_recharge_message, format_purchase_message
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Smart Card Payment System")

# Configure CORS
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Razorpay client
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

# Update Parent model
class Parent(BaseModel):
    phone: Optional[str] = None
    name: Optional[str] = None

async def get_parent_by_student_id(student_id: str) -> Optional[Parent]:
    """Get parent information from student record"""
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        return None
    
    # Only create Parent object if phone number exists
    if "parent_phone" not in student:
        return None
        
    return Parent(
        phone=student.get("parent_phone"),
        name=student.get("parent_name", "Parent")
    )

class ParentUpdate(BaseModel):
    student_id: str
    phone: str

class OTPVerification(BaseModel):
    phone_number: str
    otp_code: str
    service_sid: str

@app.get("/")
def read_root():
    return {"message": "Smart Card Payment System API"}

# Generate Vendor QR Code
@app.get("/get_vendor_qr/{vendor_id}")
async def get_vendor_qr(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Create QR code data with vendor information
    vendor_data = {
        "vendor_id": vendor_id,
        "name": vendor["name"],
        "upi_id": vendor["upi_id"]
    }
    
    qr_code_data = json.dumps(vendor_data)
    qr = qrcode.make(qr_code_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "vendor_name": vendor["name"],
        "upi_id": vendor["upi_id"],
        "balance": vendor.get("balance", 0)
    }

# Create Razorpay Order for Wallet Recharge
@app.post("/create_recharge_order")
async def create_recharge_order(request: WalletRechargeRequest):
    try:
        # Check if student exists
        student = students_collection.find_one({"student_id": request.student_id})
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        # Check if vendor exists
        vendor = vendors_collection.find_one({"vendor_id": request.vendor_id})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        # Create Razorpay order
        order_amount = int(float(request.amount) * 100)  # Convert to paise
        order_currency = 'INR'
        
        order_data = {
            'amount': order_amount,
            'currency': order_currency,
            'payment_capture': 1,  # Auto capture payment
            'notes': {
                'student_id': request.student_id,
                'vendor_id': request.vendor_id
            }
        }
        
        try:
            order = client.order.create(data=order_data)
        except Exception as e:
            print(f"Razorpay order creation error: {str(e)}")  # Debug log
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create payment order: {str(e)}"
            )

        # Create order document with date
        current_time = datetime.datetime.now()
        formatted_date = current_time.strftime("%d/%m/%Y, %H:%M:%S")
        
        order_doc = {
            "order_id": order['id'],
            "student_id": request.student_id,
            "vendor_id": request.vendor_id,
            "amount": request.amount,
            "status": "pending",
            "type": "recharge",
            "created_at": current_time,
            "formatted_date": formatted_date
        }
        
        transactions_collection.insert_one(order_doc)

        # Get parent and vendor details for SMS
        parent = await get_parent_by_student_id(request.student_id)

        if parent and parent.phone:
            message = format_recharge_message(
                amount=request.amount,
                vendor_name=vendor["name"],
                student_name=student["name"]
            )
            send_payment_notification(parent.phone, message)

        return {
            "id": order['id'],
            "amount": order_amount,
            "currency": order_currency,
            "key": os.getenv("RAZORPAY_KEY_ID")
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Order creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Verify Razorpay Payment and Update Wallet
@app.post("/verify_recharge_payment")
async def verify_recharge_payment(payment: dict):
    try:
        print("Received payment verification request:", payment)
        
        # Verify payment signature
        params_dict = {
            'razorpay_payment_id': payment.get('razorpay_payment_id'),
            'razorpay_order_id': payment.get('razorpay_order_id'),
            'razorpay_signature': payment.get('razorpay_signature')
        }

        try:
            client.utility.verify_payment_signature(params_dict)
            print("Payment signature verified successfully")  # Debug log
        except Exception as e:
            print(f"Signature verification failed: {str(e)}")  # Debug log
            raise HTTPException(
                status_code=400,
                detail=f"Payment verification failed: {str(e)}"
            )

        # Get order details from database
        order = transactions_collection.find_one({"order_id": payment['razorpay_order_id']})
        if not order:
            print(f"Order not found: {payment['razorpay_order_id']}")  # Debug log
            raise HTTPException(status_code=404, detail="Order not found")

        print("Found order:", order)  # Debug log

        # Get student and vendor details
        student = students_collection.find_one({"student_id": payment['student_id']})
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        vendor = vendors_collection.find_one({"vendor_id": payment['vendor_id']})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        # Update student's wallet balance
        student_update = students_collection.find_one_and_update(
            {"student_id": payment['student_id']},
            {"$inc": {"wallet_balance": order['amount']}},
            return_document=True
        )

        # Update vendor's balance
        vendor_update = vendors_collection.find_one_and_update(
            {"vendor_id": payment['vendor_id']},
            {"$inc": {"balance": order['amount']}},
            return_document=True
        )

        # Update order status
        current_time = datetime.datetime.now()
        formatted_date = current_time.strftime("%d/%m/%Y, %H:%M:%S")
        
        transactions_collection.update_one(
            {"order_id": payment['razorpay_order_id']},
            {
                "$set": {
                    "status": "completed",
                    "payment_id": payment['razorpay_payment_id'],
                    "completed_at": current_time,
                    "formatted_date": formatted_date
                }
            }
        )

        # Send OTP notification
        try:
            parent = await get_parent_by_student_id(payment['student_id'])
            
            if parent and parent.phone:
                message = format_recharge_message(
                    amount=order['amount'],
                    vendor_name=vendor['name'],
                    student_name=student['name']
                )
                print(f"Sending OTP to {parent.phone}")  # Debug log
                send_payment_notification(parent.phone, message)
            else:
                print("No parent phone number found for notification")  # Debug log
        except Exception as e:
            print(f"Error sending OTP notification: {str(e)}")  # Debug log

        return {
            "status": "success",
            "message": "Payment verified and processed successfully",
            "new_balance": student_update.get('wallet_balance', 0)
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Payment verification error: {str(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/student/{student_id}")
async def get_student(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Convert ObjectId to string for JSON serialization
    student["_id"] = str(student["_id"])
    return student

@app.get("/vendor/{vendor_id}")
async def get_vendor(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {
        "vendor_id": vendor["vendor_id"],
        "name": vendor["name"],
        "upi_id": vendor["upi_id"],
        "balance": vendor.get("balance", 0)  # Return 0 if balance doesn't exist
    }

# Generate Student QR Code
@app.get("/get_student_qr/{student_id}")
async def get_student_qr(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Create QR code data with student information
    qr_data = json.dumps({"student_id": student_id})
    
    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "student_name": student["name"],
        "balance": student["balance"]
    }

# Update the StudentPaymentRequest model to include password
class StudentPaymentRequest(BaseModel):
    student_id: str
    vendor_id: str
    amount: float
    description: str = ""
    password: str  # Added password field

@app.post("/process_student_payment")
async def process_student_payment(payment: StudentPaymentRequest):
    try:
        print("Processing payment request:", payment.dict())
        
        # Verify student exists and check password
        student = students_collection.find_one({"student_id": payment.student_id})
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")
        
        # Verify student password
        if payment.password != student.get("password"):
            raise HTTPException(status_code=401, detail="Invalid student password")
        
        # Check balance
        if student["balance"] < payment.amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")

        # Verify vendor exists and has sufficient balance
        vendor = vendors_collection.find_one({"vendor_id": payment.vendor_id})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
            
        if vendor.get("balance", 0) < payment.amount:
            raise HTTPException(status_code=400, detail="Insufficient vendor balance")

        # Process the transaction
        new_student_balance = student["balance"] - payment.amount
        new_vendor_balance = vendor.get("balance", 0) - payment.amount
        current_time = datetime.datetime.now()
        formatted_date = current_time.strftime("%d/%m/%Y, %H:%M:%S")
        
        # Update student balance
        students_collection.update_one(
            {"student_id": payment.student_id},
            {"$set": {"balance": new_student_balance}}
        )

        # Update vendor balance
        vendors_collection.update_one(
            {"vendor_id": payment.vendor_id},
            {"$set": {"balance": new_vendor_balance}}
        )

        # Record the transaction
        transaction = {
            "student_id": payment.student_id,
            "vendor_id": payment.vendor_id,
            "amount": payment.amount,
            "type": "purchase",
            "description": payment.description,
            "status": "completed",
            "timestamp": current_time,
            "formatted_date": formatted_date,
            "student_balance": new_student_balance,
            "vendor_balance": new_vendor_balance
        }
        transactions_collection.insert_one(transaction)

        # Send notification to parent
        try:
            parent = await get_parent_by_student_id(payment.student_id)
            if parent and parent.phone:
                message = format_purchase_message(
                    amount=payment.amount,
                    vendor_name=vendor["name"],
                    student_name=student["name"]
                )
                send_payment_notification(parent.phone, message)
        except Exception as e:
            print(f"Error sending notification: {str(e)}")

        return {
            "status": "success",
            "message": "Payment processed successfully",
            "student_balance": new_student_balance,
            "vendor_balance": new_vendor_balance,
            "transaction_date": formatted_date,
            "transaction_id": str(transaction["_id"])
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Payment processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Get Student Transactions
@app.get("/student/transactions/{student_id}")
async def get_student_transactions(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    transactions = list(transactions_collection.find(
        {"student_id": student_id},
        sort=[("created_at", -1)]  # Sort by date in descending order
    ))
    
    # Format transactions for display
    formatted_transactions = []
    for transaction in transactions:
        formatted_transaction = {
            "_id": str(transaction["_id"]),
            "date": transaction.get("formatted_date", "N/A"),
            "student_id": transaction["student_id"],
            "amount": f"₹{transaction['amount']}",
            "description": transaction.get("description", "Transaction"),
            "status": transaction["status"]
        }
        formatted_transactions.append(formatted_transaction)
    
    return {"transactions": formatted_transactions}

# Get Vendor Transactions
@app.get("/vendor/transactions/{vendor_id}")
async def get_vendor_transactions(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    transactions = list(transactions_collection.find({"vendor_id": vendor_id}))
    # Convert ObjectId to string for JSON serialization
    for transaction in transactions:
        transaction["_id"] = str(transaction["_id"])
    
    return {
        "transactions": transactions,
        "current_balance": vendor.get("balance", 0)
    }

@app.post("/update_parent_phone")
async def update_parent_phone(parent_update: ParentUpdate):
    """Update parent's phone number for a given student"""
    try:
        # Find the student and update their parent's phone number
        result = students_collection.update_one(
            {"student_id": parent_update.student_id},
            {"$set": {"parent_phone": parent_update.phone}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Student not found")
            
        return {"message": "Parent phone number updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify_otp")
async def verify_payment_otp(verification: OTPVerification):
    """Verify OTP for payment notification"""
    try:
        is_valid = verify_otp(
            verification.phone_number,
            verification.otp_code,
            verification.service_sid
        )
        return {"verified": is_valid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
