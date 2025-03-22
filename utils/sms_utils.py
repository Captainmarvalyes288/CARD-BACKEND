from twilio.rest import Client
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN

def send_payment_notification(phone_number, message):
    """
    Send OTP notification using Twilio Verify
    Args:
        phone_number (str): Recipient's phone number (format: +1234567890)
        message (str): Message content
    """
    try:
        print(f"Initializing Twilio client with SID: {TWILIO_ACCOUNT_SID}")  # Debug log
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        print(f"Sending verification to {phone_number}")  # Debug log
        verification = client.verify.v2.services \
            .create(
                friendly_name='Smart Card Payment System'
            )
        
        # Store the service SID for verification
        service_sid = verification.sid
        
        # Send the verification
        verification = client.verify.v2.services(service_sid) \
            .verifications \
            .create(to=phone_number, channel='sms')
            
        print(f"Verification sent successfully! Status: {verification.status}")  # Debug log
        return True
    except Exception as e:
        print(f"Error sending verification: {str(e)}")  # Debug log
        print(f"Twilio credentials - SID: {TWILIO_ACCOUNT_SID}")  # Debug log
        return False

def verify_otp(phone_number, otp_code, service_sid):
    """
    Verify OTP code
    Args:
        phone_number (str): Phone number that received the OTP
        otp_code (str): OTP code to verify
        service_sid (str): Twilio Verify Service SID
    """
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        verification_check = client.verify.v2.services(service_sid) \
            .verification_checks \
            .create(to=phone_number, code=otp_code)
            
        return verification_check.status == 'approved'
    except Exception as e:
        print(f"Error verifying OTP: {str(e)}")
        return False

def format_recharge_message(amount, vendor_name, student_name):
    """Format message for recharge notification"""
    message = f"Payment Alert: ₹{amount} recharged to {vendor_name} for student {student_name}."
    print(f"Formatted recharge message: {message}")  # Debug log
    return message

def format_purchase_message(amount, vendor_name, student_name):
    """Format message for purchase notification"""
    message = f"Payment Alert: Your child {student_name} made a purchase of ₹{amount} at {vendor_name}."
    print(f"Formatted purchase message: {message}")  # Debug log
    return message 