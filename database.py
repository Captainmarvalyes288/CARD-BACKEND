import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["school_payment_system"]
students_collection = db["students"]
vendors_collection = db["vendors"]
transactions_collection = db["transactions"]
