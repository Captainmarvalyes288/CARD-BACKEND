from pydantic import BaseModel
from typing import Optional

class StudentQRData(BaseModel):
    student_id: str

class PaymentRequest(BaseModel):
    vendor_id: str
    amount: float

class WalletRechargeRequest(BaseModel):
    student_id: str
    vendor_id: str
    amount: float

class VerifyPayment(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class StudentPaymentRequest(BaseModel):
    student_id: str
    vendor_id: str
    amount: float
    description: Optional[str] = None

class VendorResponse(BaseModel):
    vendor_id: str
    name: str
    upi_id: str
    balance: float
